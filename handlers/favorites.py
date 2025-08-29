import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import Forbidden
from database import db_transaction
from handlers.reputation import get_reputation_summary, build_summary_view
from html import escape

logger = logging.getLogger(__name__)

async def my_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with db_transaction() as conn:
        favorites = await conn.fetch("SELECT favorite_username FROM favorites WHERE user_id = $1 ORDER BY favorite_username", user_id)
    
    if not favorites:
        text = "🌟 **我的星盘**\n\n你的星盘空无一物。\n在求问某个存在后，点击“加入星盘”即可观测其命运轨迹。"
    else:
        fav_list = "\n".join([f"  - <code>@{escape(fav['favorite_username'])}</code>" for fav in favorites])
        text = "🌟 <b>我的星盘</b>\n" + ("-"*20) + "\n" + fav_list

    try:
        await context.bot.send_message(chat_id=user_id, text=text, parse_mode='HTML')
        if update.callback_query:
            await update.callback_query.answer("你的星盘已通过密语传达给你。", show_alert=False)
    except Forbidden:
        logger.warning(f"无法向用户 {user_id} 私信发送星盘: 用户未开启私聊")
        if update.callback_query:
            await update.callback_query.answer("❌ 无法传达密语，请先与神谕者私下交谈。", show_alert=True)
    except Exception as e:
        logger.error(f"发送星盘时发生未知错误: {e}")
        if update.callback_query:
            await update.callback_query.answer("❌ 发生未知错误，无法传达密语。", show_alert=True)

async def handle_favorite_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, action, nominee_username = query.data.split('_', 2)
    user_id = query.from_user.id

    async with db_transaction() as conn:
        if action == "add":
            await conn.execute("INSERT INTO favorites (user_id, favorite_username) VALUES ($1, $2) ON CONFLICT DO NOTHING", user_id, nominee_username)
            await query.answer("✅ 已加入星盘，你将收到关于此存在的警示。")
        elif action == "remove":
            await conn.execute("DELETE FROM favorites WHERE user_id = $1 AND favorite_username = $2", user_id, nominee_username)
            await query.answer("🗑️ 已从星盘移出。")
    
    summary = await get_reputation_summary(nominee_username, user_id)
    message_content = await build_summary_view(nominee_username, summary)
    await query.edit_message_text(**message_content)
