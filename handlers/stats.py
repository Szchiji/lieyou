import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
# 修正：将 db_fetch_val 改为正确的 db_fetchval
from database import db_fetch_all, db_fetch_one, db_fetchval

logger = logging.getLogger(__name__)

async def user_stats_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, page: int = 1):
    """显示用户的统计数据，使用 pkid"""
    query = update.callback_query
    per_page = 10
    offset = (page - 1) * per_page

    try:
        user_info = await db_fetch_one("SELECT * FROM users WHERE pkid = $1", target_user_pkid)
        if not user_info:
            await query.answer("❌ 找不到该用户。", show_alert=True)
            return
            
        display_name = user_info['first_name'] or (f"@{user_info['username']}" if user_info['username'] else f"用户 {user_info['pkid']}")

        votes = await db_fetch_all(
            """
            SELECT t.name, t.type, COUNT(v.id) as vote_count
            FROM votes v
            JOIN tags t ON v.tag_id = t.id
            WHERE v.target_user_pkid = $1
            GROUP BY t.name, t.type
            ORDER BY vote_count DESC
            LIMIT $2 OFFSET $3
            """,
            target_user_pkid, per_page, offset
        )

        # 修正：将 db_fetch_val 改为正确的 db_fetchval
        total_votes = await db_fetchval(
            "SELECT COUNT(*) FROM votes WHERE target_user_pkid = $1", target_user_pkid
        ) or 0
        total_pages = max(1, (total_votes + per_page - 1) // per_page)
        
        text = f"📊 **'{display_name}' 的统计数据 (第 {page}/{total_pages} 页)**\n\n"
        if not votes:
            text += "暂无投票数据。"
        else:
            for vote in votes:
                icon = "👍" if vote['type'] == 'recommend' else "👎"
                text += f"{icon} {vote['name']}: `{vote['vote_count']}`\n"
        
        keyboard = []
        nav_row = []
        if page > 1: nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"stats_user_{target_user_pkid}_{page-1}"))
        if page < total_pages: nav_row.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"stats_user_{target_user_pkid}_{page+1}"))
        if nav_row: keyboard.append(nav_row)
        
        keyboard.append([InlineKeyboardButton("🔙 返回声誉卡片", callback_data=f"back_to_rep_card_{target_user_pkid}")])
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"获取统计数据失败 (pkid: {target_user_pkid}): {e}", exc_info=True)
        await query.answer("❌ 获取统计数据时出错。", show_alert=True)
