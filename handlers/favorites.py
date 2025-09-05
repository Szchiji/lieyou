import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
# 修正：将 db_fetchval 改为 db_fetch_val
from database import db_execute, db_fetch_all, db_fetch_val, get_or_create_user
from .reputation import send_reputation_card

logger = logging.getLogger(__name__)

async def add_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, origin: str):
    query = update.callback_query
    user = await get_or_create_user(user_id=query.from_user.id)
    if not user:
        await query.answer("❌ 无法识别您的身份。", show_alert=True)
        return
    if user['pkid'] == target_user_pkid:
        await query.answer("❌ 你不能收藏自己。", show_alert=True)
        return
    try:
        await db_execute("INSERT INTO favorites (user_pkid, target_user_pkid) VALUES ($1, $2) ON CONFLICT DO NOTHING", user['pkid'], target_user_pkid)
        await query.answer("❤️ 已收藏！", show_alert=False)
        await send_reputation_card(update, context, target_user_pkid, origin or "fav_refresh")
    except Exception as e:
        logger.error(f"添加收藏失败: {e}", exc_info=True)
        await query.answer("❌ 添加收藏失败。", show_alert=True)

async def remove_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int):
    query = update.callback_query
    user = await get_or_create_user(user_id=query.from_user.id)
    if not user:
        await query.answer("❌ 无法识别您的身份。", show_alert=True)
        return
    try:
        await db_execute("DELETE FROM favorites WHERE user_pkid = $1 AND target_user_pkid = $2", user['pkid'], target_user_pkid)
        await query.answer("💔 已取消收藏。", show_alert=True)
        await my_favorites_list(update, context, 1)
    except Exception as e:
        logger.error(f"移除收藏失败: {e}", exc_info=True)
        await query.answer("❌ 移除收藏失败。", show_alert=True)

async def my_favorites_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    is_callback = update.callback_query is not None
    user = update.effective_user
    db_user = await get_or_create_user(user_id=user.id)
    if not db_user:
        err_msg = "❌ 无法获取您的用户信息。"
        if is_callback:
            await update.callback_query.answer(err_msg, show_alert=True)
        else:
            await update.effective_message.reply_text(err_msg)
        return
        
    per_page = 5
    offset = (page - 1) * per_page
    try:
        favs = await db_fetch_all(
            "SELECT u.pkid, u.first_name, u.username FROM favorites f JOIN users u ON f.target_user_pkid = u.pkid "
            "WHERE f.user_pkid = $1 ORDER BY f.id DESC LIMIT $2 OFFSET $3",
            db_user['pkid'], per_page, offset)
            
        # 修正：将 db_fetchval 改为 db_fetch_val
        total_favs = await db_fetch_val("SELECT COUNT(*) FROM favorites WHERE user_pkid = $1", db_user['pkid']) or 0
        total_pages = max(1, (total_favs + per_page - 1) // per_page)
        
        text = f"❤️ **我的收藏 (第 {page}/{total_pages} 页)**\n\n"
        keyboard_list = []
        if not favs:
            text += "你还没有收藏任何人。"
        else:
            for fav in favs:
                first_name = fav.get('first_name')
                username = fav.get('username')
                if first_name and first_name != username:
                    display_name = f"{first_name} (@{username})" if username else first_name
                elif username:
                    display_name = f"@{username}"
                else:
                    display_name = f"用户 {fav['pkid']}"
                callback_data = f"rep_card_query_{fav['pkid']}_fav_{page}"
                keyboard_list.append([
                    InlineKeyboardButton(f"👤 {display_name}", callback_data=callback_data),
                    InlineKeyboardButton("❌ 取消收藏", callback_data=f"remove_favorite_{fav['pkid']}")])
        
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"my_favorites_{page-1}"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"my_favorites_{page+1}"))
        if nav_row:
            keyboard_list.append(nav_row)
            
        keyboard_list.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")])
        reply_markup = InlineKeyboardMarkup(keyboard_list)
        
        if is_callback:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.effective_message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            
    except Exception as e:
        logger.error(f"获取收藏列表失败 (user pkid: {db_user.get('pkid')}): {e}", exc_info=True)
        if is_callback:
            await update.callback_query.answer("❌ 获取收藏列表时出错。", show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text("❌ 获取收藏列表时出错。")
