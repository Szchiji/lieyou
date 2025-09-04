import logging
import asyncio
from functools import lru_cache
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
    query = update.callback_query
    
    # 确保数据解析准确，不丢失下划线
    data = query.data
    user_id = query.from_user.id
    
    # 更新用户活动记录
    await update_user_activity(user_id, query.from_user.username)
    
    # 解析回调数据，这里需要更精确
    parts = data.split('_')
    if len(parts) < 2:
        await query.answer("❌ 数据格式错误", show_alert=True)
        return
        
    leaderboard_type = parts[1]  # top 或 bottom
    
    # 处理标签选择界面
    if data.endswith('_tagselect_1'):
        message_content = await build_tag_select_view(leaderboard_type)
        await query.edit_message_text(**message_content)
        return
    
    # 处理排行榜显示
    # 格式: leaderboard_type_tag_id_page
    if len(parts) >= 4:
        tag_id = parts[2]
        page = int(parts[3]) if parts[3].isdigit() else 1
        
        # 获取排行榜内容
        message_content = await get_leaderboard_view(leaderboard_type, tag_id, page)
        await query.edit_message_text(**message_content)
    else:
        await query.answer("❌ 数据格式错误", show_alert=True)

async def build_tag_select_view(leaderboard_type):
    """构建标签选择视图"""
    async with db_transaction() as conn:
        # 获取所有标签及其使用次数
        tags = await conn.fetch("""
            SELECT t.id, t.tag_name, t.type, COUNT(v.id) as usage_count
            FROM tags t 
            LEFT JOIN votes v ON t.id = v.tag_id
            GROUP BY t.id, t.tag_name, t.type
            ORDER BY usage_count DESC, t.tag_name
        """)
    
    # 按类型分组标签
    type_icon = "🏆" if leaderboard_type == "top" else "☠️"
    type_name = "英灵殿" if leaderboard_type == "top" else "放逐深渊"
    
    # 使用更美观的格式
    text = (
        f"┏━━━━「 {type_icon} <b>{type_name}</b> 」━━━━┓\n"
        "┃                          ┃\n"
        "┃  请选择要查看的箴言:        ┃\n"
        "┃                          ┃\n"
        "┗━━━━━━━━━━━━━━━━━━┛"
    )
    
    # 构建按钮
    keyboard = []
    keyboard.append([InlineKeyboardButton("✦ 全部审判 ✦", callback_data=f"leaderboard_{leaderboard_type}_all_1")])
    
    # 添加标签按钮
    active_tags = [t for t in tags if t['usage_count'] > 0]
    for tag in active_tags[:8]:  # 只显示前8个最常用的标签
        tag_name = tag['tag_name']
        if len(tag_name) > 10:
            tag_name = tag_name[:8] + ".."
        keyboard.append([InlineKeyboardButton(f"『{tag_name}』({tag['usage_count']})", callback_data=f"leaderboard_{leaderboard_type}_{tag['id']}_1")])
    
    # 添加导航按钮
    keyboard.append([InlineKeyboardButton("🌍 返回凡界", callback_data="back_to_help")])
    
    return {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}

async def get_leaderboard_view(leaderboard_type, tag_id, page=1):
    """获取排行榜数据"""
    global leaderboard_cache, leaderboard_cache_ttl
    
    # 生成缓存键
    cache_key = f"{leaderboard_type}_{tag_id}_{page}"
    
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
        # 根据tag_id决定查询条件
        if tag_id == 'all':
            # 查询所有评价
            profiles = await conn.fetch(f"""
                SELECT username, recommend_count, block_count
                FROM reputation_profiles
                WHERE recommend_count + block_count > 0
                ORDER BY (recommend_count - block_count) {order_by}, (recommend_count + block_count) DESC
                LIMIT {page_size} OFFSET {offset}
            """)
            # 获取总记录数
            total_count = await conn.fetchval("""
                SELECT COUNT(*) FROM reputation_profiles
                WHERE recommend_count + block_count > 0
            """)
            subtitle = "综合神谕"
        else:
            # 查询特定标签的评价
            tag_info = await conn.fetchrow("SELECT tag_name, type FROM tags WHERE id = $1", tag_id)
            if not tag_info:
                return {
                    'text': "❌ 错误：请求的箴言不存在。",
                    'reply_markup': InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"leaderboard_{leaderboard_type}_tagselect_1")]])
                }
            
            # 统计带有此标签的投票对每个用户的数量
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
            
            subtitle = f"箴言「{tag_info['tag_name']}」"
    
    # 计算总页数
    total_pages = (total_count + page_size - 1) // page_size or 1
    
    # 构建显示文本 - 使用更美观的格式
    text_parts = [
        f"┏━━━━「 {title_icon} <b>{title}</b> 」━━━━┓",
        f"┃                          ┃",
        f"┃  <b>{subtitle}</b>             ┃",
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
            score = (recommend - block) / (recommend + block) * 10 if recommend + block > 0 else 0
            
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
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"leaderboard_{leaderboard_type}_{tag_id}_{page-1}"))
    
    if total_pages > 1:
        nav_buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"leaderboard_{leaderboard_type}_{tag_id}_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # 返回按钮
    keyboard.append([
        InlineKeyboardButton("🔍 其他箴言", callback_data=f"leaderboard_{leaderboard_type}_tagselect_1"),
        InlineKeyboardButton("🌍 返回凡界", callback_data="back_to_help")
    ])
    
    result = {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}
    
    # 缓存结果
    leaderboard_cache[cache_key] = {
        'time': now,
        'data': result
    }
    
    return result
