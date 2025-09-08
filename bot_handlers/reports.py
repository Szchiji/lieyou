import logging
from telegram import Update
from telegram.ext import ContextTypes
import database

logger = logging.getLogger(__name__)

async def generate_my_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates and shows the user their own reputation report."""
    query = update.callback_query
    user_id = update.effective_user.id
    username = update.effective_user.username or "N/A"

    if query:
        await query.answer()

    try:
        score = await database.db_fetch_val(
            "SELECT SUM(change) FROM reputation_events WHERE target_user_id = $1", user_id
        ) or 0
        upvotes_received = await database.db_fetch_val(
            "SELECT COUNT(*) FROM reputation_events WHERE target_user_id = $1 AND change = 1", user_id
        ) or 0
        downvotes_received = await database.db_fetch_val(
            "SELECT COUNT(*) FROM reputation_events WHERE target_user_id = $1 AND change = -1", user_id
        ) or 0
        upvotes_given = await database.db_fetch_val(
            "SELECT COUNT(*) FROM reputation_events WHERE source_user_id = $1 AND change = 1", user_id
        ) or 0
        downvotes_given = await database.db_fetch_val(
            "SELECT COUNT(*) FROM reputation_events WHERE source_user_id = $1 AND change = -1", user_id
        ) or 0

        report_text = (
            f"📊 *您的个人信誉报告*\n\n"
            f"👤 用户: @{username}\n"
            f"⭐️ **总信誉分: {int(score)}**\n\n"
            f"📈 *收到的评价:*\n"
            f"  - 👍 收到赞: {upvotes_received} 次\n"
            f"  - 👎 收到踩: {downvotes_received} 次\n\n"
            f"📉 *给出的评价:*\n"
            f"  - 👍 给出赞: {upvotes_given} 次\n"
            f"  - 👎 给出踩: {downvotes_given} 次"
        )
        
        from .start import show_private_main_menu
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        
        keyboard = [[InlineKeyboardButton("返回主菜单", callback_data='show_private_main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if query:
            await query.edit_message_text(report_text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.message.reply_text(report_text, reply_markup=reply_markup, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error generating report for user {user_id}: {e}", exc_info=True)
        error_message = "生成报告时发生错误，请稍后再试。"
        if query:
            await query.edit_message_text(error_message)
        else:
            await update.message.reply_text(error_message)
