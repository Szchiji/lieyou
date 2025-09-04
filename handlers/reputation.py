import logging
import re
import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction, update_user_activity

logger = logging.getLogger(__name__)

# 评价按钮的表情
POSITIVE_EMOJI = "👍"
NEGATIVE_EMOJI = "👎"

# 缓存用户查看次数 {user_id: {target_id: last_view_time}}
user_view_cache = {}
# 缓存最近查询的用户数据 {target_id: {data}}
reputation_cache = {}
# 缓存过期时间（秒）
CACHE_EXPIRY = 300  # 5分钟

async def handle_nomination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户在群聊中提名其他用户查看声誉"""
    message = update.message
    mentioned_user = None
    
    # 尝试从正则表达式匹配中获取用户名
    match = re.search(r'@(\w{5,})', message.text)
    if match:
        username = match.group(1)
        
        # 在数据库中查找用户
        async with db_transaction() as conn:
            user_data = await conn.fetchrow(
                "SELECT id FROM users WHERE username = $1", username
            )
            if user_data:
                mentioned_user = user_data['id']
    
    if mentioned_user:
        # 更新查询发起人的活动状态
        await update_user_activity(update.effective_user.id, update.effective_user.username)
        
        # 构建信息和投票按钮
        reputation_data = await get_reputation_summary(mentioned_user, username)
        text, keyboard = create_reputation_message(reputation_data, mentioned_user)
        
        await message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

async def handle_username_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户通过"查询 @username"格式查询其他用户"""
    message = update.message
    text = message.text
    
    # 尝试从正则表达式匹配中获取用户名
    match = re.search(r'查询\s+@(\w{5,})', text)
    if not match:
        await message.reply_text("请使用格式: 查询 @用户名")
        return
    
    username = match.group(1)
    
    # 在数据库中查找用户
    async with db_transaction() as conn:
        user_data = await conn.fetchrow(
            "SELECT id FROM users WHERE username = $1", username
        )
    
    if not user_data:
        await message.reply_text(f"未找到用户 @{username}")
        return
    
    mentioned_user = user_data['id']
    
    # 更新查询发起人的活动状态
    await update_user_activity(update.effective_user.id, update.effective_user.username)
    
    # 构建信息和投票按钮
    reputation_data = await get_reputation_summary(mentioned_user, username)
    text, keyboard = create_reputation_message(reputation_data, mentioned_user)
    
    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

def create_reputation_message(data, target_id):
    """创建声誉信息显示和按钮"""
    username = data.get('username', '未知用户')
    positive = data.get('positive', 0)
    negative = data.get('negative', 0)
    total = positive + negative
    
    # 计算声誉百分比和星级显示
    reputation_pct = (positive / total * 100) if total > 0 else 50
    stars = "★" * int(reputation_pct / 20 + 0.5) + "☆" * (5 - int(reputation_pct / 20 + 0.5))
    
    # 准备评价标签显示
    top_positive_tags = data.get('top_positive_tags', [])
    top_negative_tags = data.get('top_negative_tags', [])
    
    pos_tags_text = ", ".join([f"#{tag}" for tag, _ in top_positive_tags]) if top_positive_tags else "无"
    neg_tags_text = ", ".join([f"#{tag}" for tag, _ in top_negative_tags]) if top_negative_tags else "无"
    
    # 随机选择一条箴言
    motto = data.get('random_motto', '智者仁心，常怀谨慎之思。')
    
    # 构建消息文本
    text = (
        f"🔮 **{username}** 的神谕之卷\n\n"
        f"**声誉指数:** {stars} ({reputation_pct:.1f}%)\n"
        f"**好评:** {positive} | **差评:** {negative} | **总计:** {total}\n\n"
        f"**优势标签:** {pos_tags_text}\n"
        f"**劣势标签:** {neg_tags_text}\n\n"
        f"**神谕箴言:**\n_{motto}_"
    )
    
    # 构建按钮
    keyboard = [
        [
            InlineKeyboardButton(f"{POSITIVE_EMOJI} 好评", callback_data=f"vote_positive_{target_id}"),
            InlineKeyboardButton(f"{NEGATIVE_EMOJI} 差评", callback_data=f"vote_negative_{target_id}")
        ],
        [
            InlineKeyboardButton("查看详情", callback_data=f"rep_detail_{target_id}"),
            InlineKeyboardButton("收藏", callback_data=f"query_fav_add_{target_id}")
        ],
        [
            InlineKeyboardButton("评价者", callback_data=f"rep_voters_menu_{target_id}")
        ]
    ]
    
    return text, keyboard

async def get_reputation_summary(user_id, username=None):
    """获取用户声誉摘要数据"""
    # 检查缓存
    now = datetime.now()
    if user_id in reputation_cache:
        cache_time, data = reputation_cache[user_id]
        if (now - cache_time).total_seconds() < CACHE_EXPIRY:
            return data
    
    async with db_transaction() as conn:
        # 获取基本声誉数据
        if username:
            # 如果提供了用户名，更新用户记录
            await conn.execute(
                """
                INSERT INTO users (id, username) VALUES ($1, $2)
                ON CONFLICT (id) DO UPDATE SET username = $2
                """,
                user_id, username
            )
        else:
            # 尝试获取用户名
            user_data = await conn.fetchrow("SELECT username FROM users WHERE id = $1", user_id)
            if user_data and user_data['username']:
                username = user_data['username']
            else:
                username = f"用户{user_id}"
        
        # 获取好评和差评数量
        reputation_counts = await conn.fetchrow(
            """
            SELECT 
                COUNT(*) FILTER (WHERE is_positive = TRUE) as positive,
                COUNT(*) FILTER (WHERE is_positive = FALSE) as negative
            FROM reputations
            WHERE target_id = $1
            """,
            user_id
        )
        
        positive = reputation_counts['positive'] if reputation_counts else 0
        negative = reputation_counts['negative'] if reputation_counts else 0
        
        # 获取热门标签
        positive_tags = await conn.fetch(
            """
            SELECT t.name, COUNT(*) as count
            FROM reputation_tags rt
            JOIN reputations r ON rt.reputation_id = r.id
            JOIN tags t ON rt.tag_id = t.id
            WHERE r.target_id = $1 AND r.is_positive = TRUE
            GROUP BY t.name
            ORDER BY count DESC
            LIMIT 3
            """,
            user_id
        )
        
        negative_tags = await conn.fetch(
            """
            SELECT t.name, COUNT(*) as count
            FROM reputation_tags rt
            JOIN reputations r ON rt.reputation_id = r.id
            JOIN tags t ON rt.tag_id = t.id
            WHERE r.target_id = $1 AND r.is_positive = FALSE
            GROUP BY t.name
            ORDER BY count DESC
            LIMIT 3
            """,
            user_id
        )
        
        # 获取随机箴言
        motto_row = await conn.fetchrow("SELECT content FROM mottos ORDER BY RANDOM() LIMIT 1")
        random_motto = motto_row['content'] if motto_row else "智者仁心，常怀谨慎之思。"
        
        # 组装数据
        data = {
            'username': username,
            'positive': positive,
            'negative': negative,
            'top_positive_tags': [(row['name'], row['count']) for row in positive_tags],
            'top_negative_tags': [(row['name'], row['count']) for row in negative_tags],
            'random_motto': random_motto
        }
        
        # 更新缓存
        reputation_cache[user_id] = (now, data)
        return data

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理与声誉相关的按钮点击"""
    query = update.callback_query
    user_id = update.effective_user.id
    data = query.data
    
    # 更新用户活动状态
    await update_user_activity(user_id, update.effective_user.username)
    
    try:
        if data.startswith("vote_"):
            # 处理投票
            parts = data.split("_")
            if len(parts) != 3:
                await query.answer("无效的操作", show_alert=True)
                return
            
            vote_type = parts[1]  # positive 或 negative
            target_id = int(parts[2])
            
            # 检查是否自评
            if user_id == target_id:
                await query.answer("无法评价自己", show_alert=True)
                return
            
            # 检查每日投票限制
            async with db_transaction() as conn:
                # 获取每日投票限制设置
                settings = await conn.fetchrow("SELECT value FROM settings WHERE key = 'max_daily_votes'")
                max_daily_votes = int(settings['value']) if settings else 10
                
                # 检查今日已投票数量
                today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                today_votes = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM reputations 
                    WHERE user_id = $1 AND created_at >= $2
                    """, 
                    user_id, today_start
                )
                
                # 检查是否已经评价过此用户
                existing_vote = await conn.fetchval(
                    "SELECT id FROM reputations WHERE user_id = $1 AND target_id = $2",
                    user_id, target_id
                )
                
                if existing_vote:
                    await query.answer("您已经评价过该用户", show_alert=True)
                    return
                
                if today_votes >= max_daily_votes and not existing_vote:
                    await query.answer(f"您今日的评价次数已达上限({max_daily_votes}次)", show_alert=True)
                    return
            
            # 进入评价标签选择流程
            is_positive = (vote_type == "positive")
            tag_type = "recommend" if is_positive else "block"
            
            # 获取可用标签
            async with db_transaction() as conn:
                tags = await conn.fetch(
                    "SELECT id, name FROM tags WHERE tag_type = $1 ORDER BY name",
                    tag_type
                )
            
            # 如果没有标签，先通知用户
            if not tags:
                await query.answer(f"当前没有可用的{'好评' if is_positive else '差评'}标签", show_alert=True)
                return
            
            # 创建标签选择按钮
            buttons = []
            current_row = []
            
            for tag in tags:
                tag_btn = InlineKeyboardButton(tag['name'], callback_data=f"tag_{tag['id']}_{target_id}_{is_positive}")
                current_row.append(tag_btn)
                
                if len(current_row) == 2:  # 每行两个按钮
                    buttons.append(current_row.copy())
                    current_row = []
            
            if current_row:  # 处理剩余按钮
                buttons.append(current_row)
            
            # 添加取消按钮
            buttons.append([InlineKeyboardButton("取消", callback_data="noop")])
            
            # 更新消息
            tag_type_text = "好评" if is_positive else "差评"
            await query.edit_message_text(
                f"您正在给 @{await get_username(target_id)} 添加{tag_type_text}，请选择一个标签：",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            await query.answer()
            
        elif data.startswith("tag_"):
            # 处理标签选择
            parts = data.split("_")
            if len(parts) != 4:
                await query.answer("无效的操作", show_alert=True)
                return
            
            tag_id = int(parts[1])
            target_id = int(parts[2])
            is_positive = parts[3].lower() == "true"
            
            # 创建评价记录
            async with db_transaction() as conn:
                # 创建评价
                reputation_id = await conn.fetchval(
                    """
                    INSERT INTO reputations (user_id, target_id, is_positive)
                    VALUES ($1, $2, $3)
                    RETURNING id
                    """,
                    user_id, target_id, is_positive
                )
                
                # 添加标签关联
                await conn.execute(
                    """
                    INSERT INTO reputation_tags (reputation_id, tag_id)
                    VALUES ($1, $2)
                    """,
                    reputation_id, tag_id
                )
            
            # 清除缓存
            if target_id in reputation_cache:
                del reputation_cache[target_id]
            
            # 获取更新后的声誉信息
            target_username = await get_username(target_id)
            reputation_data = await get_reputation_summary(target_id, target_username)
            text, keyboard = create_reputation_message(reputation_data, target_id)
            
            # 更新消息
            await query.edit_message_text(
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
            await query.answer("评价已添加", show_alert=True)
    
    except Exception as e:
        logger.error(f"处理按钮时发生错误: {e}", exc_info=True)
        await query.answer("操作失败，请稍后再试", show_alert=True)

async def show_reputation_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示用户声誉摘要信息"""
    query = update.callback_query
    data = query.data
    parts = data.split("_")
    
    if len(parts) < 3:
        await query.answer("无效的请求", show_alert=True)
        return
    
    target_id = int(parts[2])
    target_username = await get_username(target_id)
    
    # 更新用户活动
    await update_user_activity(update.effective_user.id, update.effective_user.username)
    
    # 获取声誉数据
    reputation_data = await get_reputation_summary(target_id, target_username)
    text, keyboard = create_reputation_message(reputation_data, target_id)
    
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    await query.answer()

async def show_reputation_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示用户声誉详细信息"""
    query = update.callback_query
    data = query.data
    parts = data.split("_")
    
    if len(parts) < 3:
        await query.answer("无效的请求", show_alert=True)
        return
    
    target_id = int(parts[2])
    user_id = update.effective_user.id
    
    # 更新用户活动
    await update_user_activity(user_id, update.effective_user.username)
    
    # 获取用户名
    target_username = await get_username(target_id)
    
    # 获取详细评价数据
    async with db_transaction() as conn:
        # 获取好评和差评的详细标签分布
        positive_tags = await conn.fetch("""
            SELECT t.name, COUNT(*) as count
            FROM reputation_tags rt
            JOIN reputations r ON rt.reputation_id = r.id
            JOIN tags t ON rt.tag_id = t.id
            WHERE r.target_id = $1 AND r.is_positive = TRUE
            GROUP BY t.name
            ORDER BY count DESC
        """, target_id)
        
        negative_tags = await conn.fetch("""
            SELECT t.name, COUNT(*) as count
            FROM reputation_tags rt
            JOIN reputations r ON rt.reputation_id = r.id
            JOIN tags t ON rt.tag_id = t.id
            WHERE r.target_id = $1 AND r.is_positive = FALSE
            GROUP BY t.name
            ORDER BY count DESC
        """, target_id)
        
        # 获取最近的评价
        recent_ratings = await conn.fetch("""
            SELECT 
                r.is_positive,
                t.name as tag_name,
                r.created_at
            FROM 
                reputations r
            JOIN 
                reputation_tags rt ON r.id = rt.reputation_id
            JOIN 
                tags t ON rt.tag_id = t.id
            WHERE 
                r.target_id = $1
            ORDER BY 
                r.created_at DESC
            LIMIT 5
        """, target_id)
    
    # 构建详细信息文本
    text = f"🔍 **{target_username}** 的详细声誉分析\n\n"
    
    # 添加好评标签分布
    if positive_tags:
        text += "**好评标签分布:**\n"
        for tag in positive_tags:
            text += f"• #{tag['name']}: {tag['count']}次\n"
        text += "\n"
    else:
        text += "**好评标签:** 暂无\n\n"
    
    # 添加差评标签分布
    if negative_tags:
        text += "**差评标签分布:**\n"
        for tag in negative_tags:
            text += f"• #{tag['name']}: {tag['count']}次\n"
        text += "\n"
    else:
        text += "**差评标签:** 暂无\n\n"
    
    # 添加最近评价
    if recent_ratings:
        text += "**最近评价:**\n"
        for rating in recent_ratings:
            date_str = rating['created_at'].strftime("%Y-%m-%d")
            vote_type = "👍" if rating['is_positive'] else "👎"
            text += f"• {date_str}: {vote_type} #{rating['tag_name']}\n"
    else:
        text += "**最近评价:** 暂无\n"
    
    # 构建按钮
    keyboard = [
        [InlineKeyboardButton("返回摘要", callback_data=f"rep_summary_{target_id}")],
        [InlineKeyboardButton("返回主菜单", callback_data="back_to_help")]
    ]
    
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    await query.answer()

async def show_voters_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示查看评价者的菜单"""
    query = update.callback_query
    data = query.data
    parts = data.split("_")
    
    if len(parts) < 3:
        await query.answer("无效的请求", show_alert=True)
        return
    
    target_id = int(parts[3])
    target_username = await get_username(target_id)
    
    # 构建菜单
    text = f"👥 选择要查看的 **{target_username}** 的评价者列表："
    
    keyboard = [
        [
            InlineKeyboardButton("👍 好评者", callback_data=f"rep_voters_positive_{target_id}"),
            InlineKeyboardButton("👎 差评者", callback_data=f"rep_voters_negative_{target_id}")
        ],
        [
            InlineKeyboardButton("返回摘要", callback_data=f"rep_summary_{target_id}")
        ]
    ]
    
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    await query.answer()

async def show_reputation_voters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示对用户进行评价的用户列表"""
    query = update.callback_query
    data = query.data
    parts = data.split("_")
    
    if len(parts) < 4:
        await query.answer("无效的请求", show_alert=True)
        return
    
    vote_type = parts[2]  # positive 或 negative
    target_id = int(parts[3])
    is_positive = vote_type == "positive"
    
    target_username = await get_username(target_id)
    
    # 获取评价者列表
    async with db_transaction() as conn:
        voters = await conn.fetch("""
            SELECT 
                r.user_id,
                u.username,
                t.name as tag_name,
                r.created_at
            FROM 
                reputations r
            JOIN 
                users u ON r.user_id = u.id
            JOIN 
                reputation_tags rt ON r.id = rt.reputation_id
            JOIN 
                tags t ON rt.tag_id = t.id
            WHERE 
                r.target_id = $1 AND r.is_positive = $2
            ORDER BY 
                r.created_at DESC
        """, target_id, is_positive)
    
    # 构建评价者列表文本
    vote_type_text = "好评" if is_positive else "差评"
    text = f"👥 给 **{target_username}** 的{vote_type_text}者 (共{len(voters)}人)\n\n"
    
    if voters:
        for i, voter in enumerate(voters, 1):
            date_str = voter['created_at'].strftime("%Y-%m-%d")
            username = voter['username'] or f"用户{voter['user_id']}"
            text += f"{i}. @{username} - #{voter['tag_name']} ({date_str})\n"
    else:
        text += f"暂无{vote_type_text}记录"
    
    # 构建按钮
    keyboard = [
        [InlineKeyboardButton("返回", callback_data=f"rep_voters_menu_{target_id}")],
        [InlineKeyboardButton("返回摘要", callback_data=f"rep_summary_{target_id}")]
    ]
    
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    await query.answer()

async def get_username(user_id):
    """获取用户名，如果不存在则返回占位符"""
    async with db_transaction() as conn:
        result = await conn.fetchrow("SELECT username FROM users WHERE id = $1", user_id)
        return result['username'] if result and result['username'] else f"用户{user_id}"
