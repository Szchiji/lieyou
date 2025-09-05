import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import db_fetch_all, db_fetchval, db_fetch_one

logger = logging.getLogger(__name__)

ITEMS_PER_PAGE = 5

async def user_stats_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int, page: int):
    """显示用户的详细统计信息，即收到的评价列表"""
    query = update.callback_query
    await query.answer()

    offset = (page - 1) * ITEMS_PER_PAGE

    try:
        # 获取目标用户信息
        target_user = await db_fetch_one("SELECT first_name, username FROM users WHERE id = $1", target_user_id)
        if not target_user:
            await query.edit_message_text("❌ 无法找到该用户。")
            return
        
        display_name = target_user['first_name'] or (f"@{target_user['username']}" if target_user['username'] else f"用户{target_user_id}")

        # 获取评价列表
        votes = await db_fetch_all(
            """
            SELECT 
                v.created_at,
                t.name as tag_name,
                t.type as tag_type,
                u.first_name as voter_name,
                u.username as voter_username,
                v.voter_user_id
            FROM votes v
            JOIN tags t ON v.tag_id = t.id
            JOIN users u ON v.voter_user_id = u.id
            WHERE v.target_user_id = $1
            ORDER BY v.created_at DESC
            LIMIT $2 OFFSET $3
            """,
            target_user_id, ITEMS_PER_PAGE, offset
        )

        total_count = await db_fetchval("SELECT COUNT(*) FROM votes WHERE target_user_id = $1", target_user_id) or 0
        total_pages = (total_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE or 1

        if not votes and page == 1:
            message = f"📊 **{display_name} 的统计数据**\n\n该用户尚未收到任何评价。"
            keyboard = [[InlineKeyboardButton("🔙 返回声誉卡片", callback_data=f"back_to_rep_card_{target_user_id}")]]
        else:
            message = f"📊 **{display_name} 的评价记录** (第 {page}/{total_pages} 页)\n\n"
            for vote in votes:
                icon = "👍" if vote['tag_type'] == 'recommend' else "👎"
                voter_display = vote['voter_name'] or (f"@{vote['voter_username']}" if vote['voter_username'] else f"ID:{vote['voter_user_id']}")
                # 将UTC时间转换为本地化显示（如果需要，可以进一步处理时区）
                vote_time = vote['created_at'].strftime('%Y-%m-%d %H:%M')
                message += f"{icon} **{vote['tag_name']}** 来自 {voter_display}\n   _{vote_time} UTC_\n"

            # 分页按钮
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"stats_user_{target_user_id}_{page-1}"))
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"stats_user_{target_user_id}_{page+1}"))

            keyboard = []
            if nav_buttons:
                keyboard.append(nav_buttons)
            keyboard.append([InlineKeyboardButton("🔙 返回声誉卡片", callback_data=f"back_to_rep_card_{target_user_id}")])

        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"获取用户统计失败 (target: {target_user_id}): {e}", exc_info=True)
        await query.edit_message_text("❌ 获取统计数据时出错。")
