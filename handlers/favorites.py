import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction
from handlers.reputation import get_reputation_summary, build_summary_view
from html import escape

logger = logging.getLogger(__name__)

async def my_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with db_transaction() as conn:
        favorites = await conn.fetch("SELECT favorite_username FROM favorites WHERE user_id = $1 ORDER BY favorite_username", user_id)
    
    if not favorites:
        text = "🌟 **我的收藏夹**\n\n您的收藏夹是空的。\n在查询用户后，点击“收藏”即可添加。"
    else:
        fav_list = "\n".join([f"  - <code>@{escape(fav['favorite_username'])}</code>" for fav in favorites])
        text = "🌟 <b>我的收藏夹</b>\n" + ("-"*20) + "\n" + fav_list

    try:
        await context.bot.send_message(chat_id=user_id, text=text, parse_mode='HTML')
        if update.callback_query:
            await update.callback_query.answer("已将您的收藏列表私信给您。", show_alert=False)
        elif update.message:
            # 如果是命令触发，可以考虑在群里给一个短暂的确认
            pass
    except Exception as e:
        logger.warning(f"无法向用户 {user_id} 私信发送收藏夹: {e}")
        if update.callback_query:
            await update.callback_query.answer("❌ 无法私信，请先与我私聊。", show_alert=True)

async def handle_favorite_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, nominee_username = query.data.split('_', 2)[1:]
    user_id = query.from_user.id

    async with db_transaction() as conn:
        if action == "add":
            await conn.execute("INSERT INTO favorites (user_id, favorite_username) VALUES ($1, $2) ON CONFLICT DO NOTHING", user_id, nominee_username)
            await query.answer("✅ 已加入收藏！", show_alert=False)
        elif action == "remove":
            await conn.execute("DELETE FROM favorites WHERE user_id = $1 AND favorite_username = $2", user_id, nominee_username)
            await query.answer("🗑️ 已移出收藏。", show_alert=False)
    
    summary = await get_reputation_summary(nominee_username, user_id)
    message_content = await build_summary_view(nominee_username, summary)
    await query.edit_message_text(**message_content)
