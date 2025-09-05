import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from database import db_execute, db_fetch_all, get_or_create_user

logger = logging.getLogger(__name__)

async def add_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int):
    query = update.callback_query
    user = await get_or_create_user(user_id=query.from_user.id)
    
    if user['pkid'] == target_user_pkid:
        await query.answer("❌ 你不能收藏自己。", show_alert=True)
        return

    try:
        await db_execute(
            "INSERT INTO favorites (user_pkid, target_user_pkid) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            user['pkid'], target_user_pkid
        )
        await query.answer("❤️ 已收藏！", show_alert=True)
    except Exception as e:
        logger.error(f"添加收藏失败: {e}")
        await query.answer("❌ 添加收藏失败。", show_alert=True)

async def remove_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int):
    query = update.callback_query
    user = await get_or_create_user(user_id=query.from_user.id)
    try:
        await db_execute(
            "DELETE FROM favorites WHERE user_pkid = $1 AND target_user_pkid = $2",
            user['pkid'], target_user_pkid
        )
        await query.answer("💔 已取消收藏。", show_alert=True)
        # 刷新收藏列表
        await my_favorites_list(update, context, 1)
    except Exception as e:
        logger.error(f"移除收藏失败: {e}")
        await query.answer("❌ 移除收藏失败。", show_alert=True)

async def my_favorites_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    query = update.callback_query
    user = await get_or_create_user(user_id=update.effective_user.id)
    
    per_page = 10
    offset = (page - 1) * per_page
    
    try:
        favs = await db_fetch_all(
            """
            SELECT u.pkid, u.first_name, u.username FROM favorites f
            JOIN users u ON f.target_user_pkid = u.pkid
            WHERE f.user_pkid = $1 ORDER BY u.first_name, u.username
            LIMIT $2 OFFSET $3
            """,
            user['pkid'], per_page, offset
        )
        
        total_favs = await db_fetch_val(
            "SELECT COUNT(*) FROM favorites WHERE user_pkid = $1", user['pkid']
        ) or 0
        total_pages = (total_favs + per_page - 1) // per_page

        text = "❤️ **我的收藏**\n\n"
        keyboard = []
        if not favs:
            text += "你还没有收藏任何人。"
        else:
            for fav in favs:
                display_name = fav['first_name'] or f"@{fav['username']}"
                keyboard.append([
                    InlineKeyboardButton(display_name, callback_data=f"rep_card_query_{fav['pkid']}"),
                    InlineKeyboardButton("❌", callback_data=f"remove_favorite_{fav['pkid']}")
                ])
        
        # 分页按钮
        nav_row = []
        if page > 1: nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"my_favorites_{page-1}"))
        if page < total_pages: nav_row.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"my_favorites_{page+1}"))
        if nav_row: keyboard.append(nav_row)

        keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")])
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"获取收藏列表失败 (user: {user['pkid']}): {e}", exc_info=True)
        await query.answer("❌ 获取收藏列表时出错。", show_alert=True)
