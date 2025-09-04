import logging
import asyncio
from time import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction, update_user_activity
from html import escape

logger = logging.getLogger(__name__)

# 缓存控制
leaderboard_cache = {}
leaderboard_cache_ttl = 300  # 默认5分钟

async def get_cache_ttl():
    """获取排行榜缓存时间"""
    async with db_transaction() as conn:
        result = await conn.fetchval("SELECT value FROM settings WHERE key = 'leaderboard_cache_ttl'")
        if result:
            return int(result)
    return 300  # 默认5分钟

def clear_leaderboard_cache():
    """清空排行榜缓存"""
    global leaderboard_cache
    leaderboard_cache = {}
    logger.info("排行榜缓存已清空")

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示用户排行榜"""
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    
    # 更新用户活动记录
    await update_user_activity(user_id, query.from_user.username)
    
    # 解析回调数据
    parts = data.split('_')
    if len(parts) < 2:
        await query.answer("❌ 数据格式错误", show_alert=True)
        return
    
    leaderboard_type = parts[1]  # top 或 bottom
    
    # 如果是直接点击英灵殿或放逐深渊，显示用户排行榜
    if len(parts) == 3 and parts[2] == "tagselect":
        # 直接显示用户排行榜，不再显示标签选择
        message_content = await get_user_leaderboard(leaderboard_type, 1)
        await query.edit_message_text(**message_content)
        return
        
    # 处理页码导航
    if len(parts) >= 3 and parts[2] == "page":
        page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
        message_content = await get_user_leaderboard(leaderboard_type, page)
        await query.edit_message_text(**message_content)
        return
    
    # 处理特定箴言的排行
    if len(parts) >= 3 and parts[2] == "tag":
        tag_id = int(parts[3])
        page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
        message_content = await get_tag_leaderboard(leaderboard_type, tag_id, page)
        await query.edit_message_text(**message_content)
        return
    
    # 默认显示用户排行榜第一页
    message_content = await get_user_leaderboard(leaderboard_type, 1)
    await query.edit_message_text(**message_content)

async def get_user_leaderboard(leaderboard_type, page=1):
    """获取用户排行榜数据"""
    global leaderboard_cache
    
    # 生成缓存键
    cache_key = f"user_{leaderboard_type}_{page}"
    
    # 检查缓存
    now = time()
    ttl = await get_cache_ttl()
    if cache_key in leaderboard_cache and now - leaderboard_cache[cache_key]['time'] < ttl:
        return leaderboard_cache[cache_key]['data']
    
    # 准备SQL查询
    page_size = 10
    offset = (page - 1) * page_size
    
    # 确定排序方向和标题
    order_by = "DESC" if leaderboard_type == "top" else "ASC"
    title_icon = "🏆" if leaderboard_type == "top" else "☠️"
    title = "英灵殿" if leaderboard_type == "top" else "放逐深渊"
    
    async with db_transaction() as conn:
        # 查询用户排行
        profiles = await conn.fetch(f"""
            SELECT 
                rp.username, 
                rp.recommend_count, 
                rp.block_count,
                (
                    SELECT array_agg(DISTINCT t.tag_name) 
                    FROM votes v 
                    JOIN tags t ON v.tag_id = t.id 
                    WHERE v.nominee_username = rp.username AND v.vote_type = $1
                    LIMIT 3
                ) AS top_tags
            FROM reputation_profiles rp
            WHERE rp.recommend_count + rp.block_count > 0
            ORDER BY 
                CASE WHEN $1 = 'recommend' THEN rp.recommend_count ELSE -rp.block_count END {order_by},
                rp.recommend_count + rp.block_count DESC
            LIMIT {page_size} OFFSET {offset}
        """, "recommend" if leaderboard_type == "top" else "block")
        
        # 获取总记录数
        total_count = await conn.fetchval("""
            SELECT COUNT(*) FROM reputation_profiles
            WHERE recommend_count + block_count > 0
        """)
    
    # 计算总页数
    total_pages = (total_count + page_size - 1) // page_size or 1
    
    # 构建显示文本
    text_parts = [
        f"┏━━━━「 {title_icon} <b>{title}</b> 」━━━━┓",
        f"┃                          ┃",
        f"┃  <b>用户排行榜</b>              ┃",
        f"┃                          ┃"
    ]
    
    if not profiles:
        text_parts.append("┃  暂无相关记录。          ┃")
    else:
        for i, profile in enumerate(profiles):
            rank = offset + i + 1
            username = profile['username']
            recommend = profile['recommend_count']
            block = profile['block_count']
            
            # 计算声誉分数
            if recommend + block > 0:
                score = round((recommend - block) / (recommend + block) * 10, 1)
            else:
                score = 0
                
            # 根据分数确定图标
            if score >= 7:
                icon = "🌟"
            elif score >= 3:
                icon = "✨"
            elif score >= -3:
                icon = "⚖️"
            elif score >= -7:
                icon = "⚠️"
            else:
                icon = "☠️"
            
            # 获取最常见的标签
            tags = profile['top_tags'] or []
            tags_text = ", ".join([f"『{tag}』" for tag in tags[:2]]) if tags else "无主要箴言"
            
            # 添加用户行
            text_parts.append(f"┃  {rank}. <b>@{escape(username)}</b> {icon} ({score:.1f})  ┃")
            if tags:
                text_parts.append(f"┃     箴言: {tags_text[:20]}..  ┃")
    
    text_parts.extend([
        "┃                          ┃",
        "┗━━━━━━━━━━━━━━━━━━┛"
    ])
    
    text = "\n".join(text_parts)
    
    # 构建分页按钮
    keyboard = []
    nav_buttons = []
    
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"leaderboard_{leaderboard_type}_page_{page-1}"))
    
    if total_pages > 1:
        nav_buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"leaderboard_{leaderboard_type}_page_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # 添加箴言排行查看按钮
    async with db_transaction() as conn:
        # 获取最常用的箴言
        popular_tags = await conn.fetch("""
            SELECT t.id, t.tag_name, COUNT(v.id) as usage_count
            FROM tags t
            JOIN votes v ON v.tag_id = t.id
            WHERE t.type = $1
            GROUP BY t.id, t.tag_name
            ORDER BY usage_count DESC
            LIMIT 4
        """, "recommend" if leaderboard_type == "top" else "block")
        
    if popular_tags:
        keyboard.append([InlineKeyboardButton("📊 查看箴言排行", callback_data="noop")])
        for tag in popular_tags:
            tag_name = tag['tag_name']
            if len(tag_name) > 10:
                tag_name = tag_name[:8] + ".."
            keyboard.append([
                InlineKeyboardButton(
                    f"『{tag_name}』({tag['usage_count']}次)", 
                    callback_data=f"leaderboard_{leaderboard_type}_tag_{tag['id']}_1"
                )
            ])
    
    # 添加返回按钮
    keyboard.append([InlineKeyboardButton("🌍 返回凡界", callback_data="back_to_help")])
    
    result = {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}
    
    # 缓存结果
    leaderboard_cache[cache_key] = {
        'time': now,
        'data': result
    }
    
    return result

async def get_tag_leaderboard(leaderboard_type, tag_id, page=1):
    """获取特定箴言的排行榜"""
    global leaderboard_cache
    
    # 生成缓存键
    cache_key = f"tag_{leaderboard_type}_{tag_id}_{page}"
    
    # 检查缓存
    now = time()
    ttl = await get_cache_ttl()
    if cache_key in leaderboard_cache and now - leaderboard_cache[cache_key]['time'] < ttl:
        return leaderboard_cache[cache_key]['data']
    
    # 准备SQL查询
    page_size = 10
    offset = (page - 1) * page_size
    
    async with db_transaction() as conn:
        # 获取标签信息
        tag_info = await conn.fetchrow("SELECT tag_name, type FROM tags WHERE id = $1", tag_id)
        if not tag_info:
            return {
                'text': "❌ 错误：请求的箴言不存在。",
                'reply_markup': InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"leaderboard_{leaderboard_type}_page_1")]])
            }
        
        # 确定排序方向和标题
        order_by = "DESC" if leaderboard_type == "top" else "ASC"
        title_icon = "🏆" if leaderboard_type == "top" else "☠️"
        title = "英灵殿" if leaderboard_type == "top" else "放逐深渊"
        
        # 获取带有该标签的用户列表
        profiles = await conn.fetch(f"""
            SELECT v.nominee_username as username, 
                   COUNT(CASE WHEN v.vote_type = 'recommend' THEN 1 END) as recommend_count,
                   COUNT(CASE WHEN v.vote_type = 'block' THEN 1 END) as block_count
            FROM votes v
            WHERE v.tag_id = $1
            GROUP BY v.nominee_username
            ORDER BY (COUNT(CASE WHEN v.vote_type = 'recommend' THEN 1 END) - 
                     COUNT(CASE WHEN v.vote_type = 'block' THEN 1 END)) {order_by},
                     (COUNT(CASE WHEN v.vote_type = 'recommend' THEN 1 END) + 
                     COUNT(CASE WHEN v.vote_type = 'block' THEN 1 END)) DESC
            LIMIT {page_size} OFFSET {offset}
        """, tag_id)
        
        # 获取总记录数
        total_count = await conn.fetchval("""
            SELECT COUNT(DISTINCT nominee_username) FROM votes
            WHERE tag_id = $1
        """, tag_id)
    
    # 计算总页数
    total_pages = (total_count + page_size - 1) // page_size or 1
    
    # 构建显示文本
    text_parts = [
        f"┏━━━━「 {title_icon} <b>{title}</b> 」━━━━┓",
        f"┃                          ┃",
        f"┃  <b>箴言排行:</b>             ┃",
        f"┃  『{escape(tag_info['tag_name'])}』      ┃",
        f"┃                          ┃"
    ]
    
    if not profiles:
        text_parts.append("┃  暂无相关记录。          ┃")
    else:
        for i, profile in enumerate(profiles):
            rank = offset + i + 1
            username = profile['username']
            recommend = profile['recommend_count']
            block = profile['block_count']
            
            # 计算声誉分数
            if recommend + block > 0:
                score = round((recommend - block) / (recommend + block) * 10, 1)
            else:
                score = 0
                
            # 根据分数确定图标
            if score >= 7:
                icon = "🌟"
            elif score >= 3:
                icon = "✨"
            elif score >= -3:
                icon = "⚖️"
            elif score >= -7:
                icon = "⚠️"
            else:
                icon = "☠️"
            
            # 添加用户行
            text_parts.append(f"┃  {rank}. <b>@{escape(username)}</b> {icon} ({score:.1f})  ┃")
    
    text_parts.extend([
        "┃                          ┃",
        "┗━━━━━━━━━━━━━━━━━━┛"
    ])
    
    text = "\n".join(text_parts)
    
    # 构建分页按钮
    keyboard = []
    nav_buttons = []
    
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"leaderboard_{leaderboard_type}_tag_{tag_id}_{page-1}"))
    
    if total_pages > 1:
        nav_buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"leaderboard_{leaderboard_type}_tag_{tag_id}_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # 添加返回按钮
    keyboard.append([
        InlineKeyboardButton("⬅️ 返回用户排行", callback_data=f"leaderboard_{leaderboard_type}_page_1"),
        InlineKeyboardButton("🌍 返回凡界", callback_data="back_to_help")
    ])
    
    result = {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}
    
    # 缓存结果
    leaderboard_cache[cache_key] = {
        'time': now,
        'data': result
    }
    
    return result
