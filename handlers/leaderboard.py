import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_cursor

logger = logging.getLogger(__name__)

async def get_top_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示推荐榜 (声望高的)"""
    async with db_cursor() as cur:
        users = await cur.fetch("""
            SELECT full_name, username, reputation FROM users 
            WHERE username IS NOT NULL AND username != 'GroupAnonymousBot'
            ORDER BY reputation DESC, id ASC
            LIMIT 10
        """)
    
    text = "🏆 **推荐排行榜** 🏆\n\n"
    if not users:
        text += "排行榜是空的。"
    else:
        text += "\n".join([f"{i+1}. {u['full_name']} (@{u['username']}) - 声望: {u['reputation']}" for i, u in enumerate(users)])
    
    keyboard = [[InlineKeyboardButton("🔄 刷新", callback_data="leaderboard_refresh_top")]]
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def get_bottom_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示拉黑榜 (声望低的)"""
    async with db_cursor() as cur:
        users = await cur.fetch("""
            SELECT full_name, username, reputation FROM users 
            WHERE username IS NOT NULL AND username != 'GroupAnonymousBot'
            ORDER BY reputation ASC, id ASC
            LIMIT 10
        """)

    text = "☠️ **拉黑排行榜** ☠️\n\n"
    if not users:
        text += "排行榜是空的。"
    else:
        text += "\n".join([f"{i+1}. {u['full_name']} (@{u['username']}) - 声望: {u['reputation']}" for i, u in enumerate(users)])
    
    keyboard = [[InlineKeyboardButton("🔄 刷新", callback_data="leaderboard_refresh_bottom")]]
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))


async def leaderboard_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理排行榜刷新按钮。"""
    query = update.callback_query
    await query.answer()
    
    action = query.data
    
    if action == "leaderboard_refresh_top":
        await get_top_board(query, context)
    elif action == "leaderboard_refresh_bottom":
        await get_bottom_board(query, context)
