import logging
import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from database import db_execute, db_fetch_all, db_fetchval, get_or_create_user

logger = logging.getLogger(__name__)

async def add_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int):
    query = update.callback_query
    user = await get_or_create_user(user_id=query.from_user.id)
    if not user: await query.answer("❌ 无法识别您的身份。", show_alert=True); return
    if user['pkid'] == target_user_pkid: await query.answer("❌ 你不能收藏自己。", show_alert=True); return
    try:
        await db_execute("INSERT INTO favorites (user_pkid, target_user_pkid) VALUES ($1, $2) ON CONFLICT DO NOTHING", user['pkid'], target_user_pkid)
        await query.answer("❤️ 已收藏！", show_alert=True)
    except Exception as e:
        logger.error(f"添加收藏失败: {e}", exc_info=True); await query.answer("❌ 添加收藏失败。", show_alert=True)

async def remove_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int):
    query = update.callback_query
    user = await get_or_create_user(user_id=query.from_user.id)
    if not user: await query.answer("❌ 无法识别您的身份。", show_alert=True); return
    try:
        await db_execute("DELETE FROM favorites WHERE user_pkid = $1 AND target_user_pkid = $2", user['pkid'], target_user_pkid)
        await query.answer("💔 已取消收藏。", show_alert=True)
        await my_favorites_list(update, context, 1)
    except Exception as e:
        logger.error(f"移除收藏失败: {e}", exc_info=True); await query.answer("❌ 移除收藏失败。", show_alert=True)

async def my_favorites_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    is_callback = update.callback_query is not None
    user = update.effective_user
    chat_type = update.effective_chat.type
    db_user = await get_or_create_user(user_id=user.id)
    if not db_user:
        err_msg = "❌ 无法获取您的用户信息。"
        if is_callback: await update.callback_query.answer(err_msg, show_alert=True)
        else: await update.effective_message.reply_text(err_msg)
        return
    per_page = 5
    offset = (page - 1) * per_page
    try:
        favs = await db_fetch_all(
            "SELECT u.pkid, u.first_name, u.username FROM favorites f JOIN users u ON f.target_user_pkid = u.pkid "
            "WHERE f.user_pkid = $1 ORDER BY u.first_name, u.username LIMIT $2 OFFSET $3",
            db_user['pkid'], per_page, offset)
        total_favs = await db_fetchval("SELECT COUNT(*) FROM favorites WHERE user_pki
