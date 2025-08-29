from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_cursor

async def get_top_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_leaderboard(update, "推荐", "DESC")

async def get_bottom_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_leaderboard(update, "拉黑", "ASC")

async def send_leaderboard(update: Update, title, order):
    async with db_cursor() as cur:
        users = await cur.fetch(f"SELECT full_name, username, reputation FROM users ORDER BY reputation {order} LIMIT 10")
    
    text = f"🏆 **{title}排行榜** 🏆\n\n"
    text += "\n".join([f"{i+1}. {u['full_name']} (@{u['username']}) - 声望: {u['reputation']}" for i, u in enumerate(users)])
    
    keyboard = [[InlineKeyboardButton("刷新", callback_data=f"leaderboard_refresh_{title}_{order}")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def leaderboard_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("正在刷新...")
    _, _, title, order = query.data.split('_')
    
    async with db_cursor() as cur:
        users = await cur.fetch(f"SELECT full_name, username, reputation FROM users ORDER BY reputation {order} LIMIT 10")
        
    text = f"🏆 **{title}排行榜** 🏆\n\n"
    text += "\n".join([f"{i+1}. {u['full_name']} (@{u['username']}) - 声望: {u['reputation']}" for i, u in enumerate(users)])
    
    keyboard = [[InlineKeyboardButton("刷新", callback_data=f"leaderboard_refresh_{title}_{order}")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
