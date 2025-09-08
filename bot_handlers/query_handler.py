import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from database import save_user, db_fetch_all, db_fetch_one, db_execute
from .user_handler import get_user_display_name, get_user_from_message

logger = logging.getLogger(__name__)

async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle user queries from mentions, forwards, or callbacks."""
    
    if update.callback_query:
        await handle_callback_query(update, context)
    else:
        await handle_message_query(update, context)

async def handle_message_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle queries from messages (mentions, forwards, replies)."""
    message = update.message
    if not message:
        return
    
    # Get the target user
    target_user = await get_user_from_message(message)
    if not target_user:
        await message.reply_text("❌ 无法识别目标用户。请 @用户名、转发消息或回复消息。")
        return
    
    # Save users to database
    await save_user(message.from_user)
    target_user_pkid = await save_user(target_user)
    
    # Get user reputation
    reputation = await get_user_reputation(target_user_pkid)
    
    # Create inline keyboard
    keyboard = [
        [
            InlineKeyboardButton("👍 推荐", callback_data=f"rate_recommend_{target_user.id}"),
            InlineKeyboardButton("👎 警告", callback_data=f"rate_warn_{target_user.id}")
        ],
        [InlineKeyboardButton("❤️ 收藏", callback_data=f"favorite_{target_user.id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Format response
    response = format_user_info(target_user, reputation)
    
    await message.reply_text(
        response,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback queries from inline keyboards."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user = query.from_user
    
    # Save user
    user_pkid = await save_user(user)
    
    if data.startswith("rate_"):
        await handle_rating(query, user_pkid, data)
    elif data.startswith("favorite_"):
        await handle_favorite(query, user_pkid, data)
    elif data.startswith("tag_"):
        await handle_tag_selection(query, user_pkid, data)
    elif data == "show_leaderboard":
        await show_leaderboard(query)
    elif data == "show_my_favorites":
        await show_favorites(query, user_pkid)
    elif data == "show_help":
        await show_help(query)

async def handle_rating(query, user_pkid: int, data: str) -> None:
    """Handle rating selection."""
    _, rating_type, target_id = data.split("_")
    
    # Get available tags
    tags = await db_fetch_all(
        "SELECT pkid, name FROM tags WHERE type = $1 AND is_active = TRUE",
        rating_type
    )
    
    if not tags:
        await query.edit_message_text("❌ 暂无可用标签")
        return
    
    # Create tag selection keyboard
    keyboard = []
    for tag in tags:
        keyboard.append([
            InlineKeyboardButton(
                tag['name'], 
                callback_data=f"tag_{rating_type}_{target_id}_{tag['pkid']}"
            )
        ])
    keyboard.append([InlineKeyboardButton("❌ 取消", callback_data="cancel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    tag_type = "推荐" if rating_type == "recommend" else "警告"
    await query.edit_message_text(
        f"请选择一个{tag_type}标签：",
        reply_markup=reply_markup
    )

async def handle_tag_selection(query, user_pkid: int, data: str) -> None:
    """Handle tag selection for rating."""
    _, rating_type, target_id, tag_pkid = data.split("_")
    
    target_id = int(target_id)
    tag_pkid = int(tag_pkid)
    
    # Get target user pkid
    target_user = await db_fetch_one(
        "SELECT pkid FROM users WHERE id = $1",
        target_id
    )
    
    if not target_user:
        await query.edit_message_text("❌ 用户不存在")
        return
    
    # Check if already rated with this tag
    existing = await db_fetch_one(
        """SELECT 1 FROM evaluations 
        WHERE evaluator_user_pkid = $1 
        AND target_user_pkid = $2 
        AND tag_pkid = $3""",
        user_pkid, target_user['pkid'], tag_pkid
    )
    
    if existing:
        await query.edit_message_text("❌ 您已经使用过这个标签评价该用户")
        return
    
    # Add evaluation
    await db_execute(
        """INSERT INTO evaluations 
        (evaluator_user_pkid, target_user_pkid, tag_pkid, type) 
        VALUES ($1, $2, $3, $4)""",
        user_pkid, target_user['pkid'], tag_pkid, rating_type
    )
    
    await query.edit_message_text("✅ 评价成功！")

async def handle_favorite(query, user_pkid: int, data: str) -> None:
    """Handle favorite/unfavorite action."""
    _, target_id = data.split("_")
    target_id = int(target_id)
    
    # Get target user pkid
    target_user = await db_fetch_one(
        "SELECT pkid FROM users WHERE id = $1",
        target_id
    )
    
    if not target_user:
        await query.edit_message_text("❌ 用户不存在")
        return
    
    # Check if already favorited
    existing = await db_fetch_one(
        """SELECT 1 FROM favorites 
        WHERE user_pkid = $1 AND target_user_pkid = $2""",
        user_pkid, target_user['pkid']
    )
    
    if existing:
        # Remove favorite
        await db_execute(
            """DELETE FROM favorites 
            WHERE user_pkid = $1 AND target_user_pkid = $2""",
            user_pkid, target_user['pkid']
        )
        await query.edit_message_text("💔 已取消收藏")
    else:
        # Add favorite
        await db_execute(
            """INSERT INTO favorites (user_pkid, target_user_pkid) 
            VALUES ($1, $2)""",
            user_pkid, target_user['pkid']
        )
        await query.edit_message_text("❤️ 收藏成功！")

async def show_leaderboard(query) -> None:
    """Show reputation leaderboard."""
    # Get top recommended users
    top_recommended = await db_fetch_all("""
        SELECT u.id, u.username, u.first_name, u.last_name, COUNT(*) as count
        FROM evaluations e
        JOIN users u ON e.target_user_pkid = u.pkid
        WHERE e.type = 'recommend' AND u.is_hidden = FALSE
        GROUP BY u.id, u.username, u.first_name, u.last_name
        ORDER BY count DESC
        LIMIT 10
    """)
    
    # Get top warned users
    top_warned = await db_fetch_all("""
        SELECT u.id, u.username, u.first_name, u.last_name, COUNT(*) as count
        FROM evaluations e
        JOIN users u ON e.target_user_pkid = u.pkid
        WHERE e.type = 'warn' AND u.is_hidden = FALSE
        GROUP BY u.id, u.username, u.first_name, u.last_name
        ORDER BY count DESC
        LIMIT 10
    """)
    
    response = "📊 *信誉排行榜*\n\n"
    
    if top_recommended:
        response += "*👍 最受推荐*\n"
        for i, user in enumerate(top_recommended, 1):
            name = get_user_display_name(user)
            response += f"{i}. {name} - {user['count']} 推荐\n"
    
    if top_warned:
        response += "\n*👎 最多警告*\n"
        for i, user in enumerate(top_warned, 1):
            name = get_user_display_name(user)
            response += f"{i}. {name} - {user['count']} 警告\n"
    
    await query.edit_message_text(response, parse_mode=ParseMode.MARKDOWN)

async def show_favorites(query, user_pkid: int) -> None:
    """Show user's favorites."""
    favorites = await db_fetch_all("""
        SELECT u.id, u.username, u.first_name, u.last_name
        FROM favorites f
        JOIN users u ON f.target_user_pkid = u.pkid
        WHERE f.user_pkid = $1
        ORDER BY f.created_at DESC
    """, user_pkid)
    
    if not favorites:
        await query.edit_message_text("您还没有收藏任何用户")
        return
    
    response = "❤️ *我的收藏*\n\n"
    for user in favorites:
        name = get_user_display_name(user)
        response += f"• {name}\n"
    
    await query.edit_message_text(response, parse_mode=ParseMode.MARKDOWN)

async def show_help(query) -> None:
    """Show help message."""
    help_text = """
❓ *帮助信息*

*查询用户信誉*
• 在群组中 @用户名
• 转发用户的消息
• 回复用户的消息

*评价用户*
• 点击查询结果下方的 👍推荐 或 👎警告
• 选择合适的标签

*其他功能*
• 📊 查看排行榜：查看信誉最好和最差的用户
• ❤️ 我的收藏：查看和管理收藏的用户
• 🔍 搜索功能：即将推出

*注意事项*
• 请诚实评价，恶意评价将被封禁
• 每个标签对每个用户只能使用一次
"""
    await query.edit_message_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def get_user_reputation(user_pkid: int) -> dict:
    """Get user's reputation summary."""
    # Get recommendation count by tags
    recommends = await db_fetch_all("""
        SELECT t.name, COUNT(*) as count
        FROM evaluations e
        JOIN tags t ON e.tag_pkid = t.pkid
        WHERE e.target_user_pkid = $1 AND e.type = 'recommend'
        GROUP BY t.name
    """, user_pkid)
    
    # Get warning count by tags
    warns = await db_fetch_all("""
        SELECT t.name, COUNT(*) as count
        FROM evaluations e
        JOIN tags t ON e.tag_pkid = t.pkid
        WHERE e.target_user_pkid = $1 AND e.type = 'warn'
        GROUP BY t.name
    """, user_pkid)
    
    return {
        'recommends': recommends,
        'warns': warns,
        'total_recommends': sum(r['count'] for r in recommends),
        'total_warns': sum(w['count'] for w in warns)
    }

def format_user_info(user, reputation: dict) -> str:
    """Format user information for display."""
    name = get_user_display_name(user)
    user_id = user.id
    
    response = f"👤 *用户信息*\n"
    response += f"姓名：{name}\n"
    response += f"ID：`{user_id}`\n\n"
    
    response += f"📊 *信誉统计*\n"
    response += f"👍 推荐：{reputation['total_recommends']} 次\n"
    response += f"👎 警告：{reputation['total_warns']} 次\n"
    
    if reputation['recommends']:
        response += "\n*推荐详情：*\n"
        for rec in reputation['recommends']:
            response += f"• {rec['name']}：{rec['count']} 次\n"
    
    if reputation['warns']:
        response += "\n*警告详情：*\n"
        for warn in reputation['warns']:
            response += f"• {warn['name']}：{warn['count']} 次\n"
    
    return response
