import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from math import ceil

from database import db_fetch_all, db_fetch_val
from .utils import membership_required

logger = logging.getLogger(__name__)

STATS_PAGE_SIZE = 5

@membership_required
async def show_user_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE, target_pkid: int, page: int, target_username: str):
    """显示用户的详细统计信息，主要是评价者列表。"""
    query = update.callback_query
    await query.answer()

    total_evals = await db_fetch_val("SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = $1", target_pkid)
    
    if total_evals == 0:
        text = f"📊 **@{target_username} 的统计数据**\n\n该用户还没有收到任何评价。"
        keyboard = [[InlineKeyboardButton("🔙 返回声誉卡片", callback_data=f"back_to_rep_card_{target_pkid}_{target_username}")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    total_pages = ceil(total_evals / STATS_PAGE_SIZE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * STATS_PAGE_SIZE

    evaluations = await db_fetch_all(
        """
        SELECT u.username as evaluator, t.name as tag_name, e.type as eval_type
        FROM evaluations e
        JOIN users u ON e.user_pkid = u.pkid
        JOIN tags t ON e.tag_pkid = t.pkid
        WHERE e.target_user_pkid = $1
        ORDER BY e.created_at DESC
        LIMIT $2 OFFSET $3
        """,
        target_pkid, STATS_PAGE_SIZE, offset
    )

    text = f"📊 **@{target_username} 的评价记录** (第 {page}/{total_pages} 页)\n\n"
    for eval in evaluations:
        icon = "👍" if eval['eval_type'] == 'recommend' else "👎"
        text += f"{icon} @{eval['evaluator']} 评价为 **{eval['tag_name']}**\n"

    pagination_row = []
    if page > 1:
        pagination_row.append(InlineKeyboardButton("⬅️", callback_data=f"stats_user_{target_pkid}_{page-1}_{target_username}"))
    if page < total_pages:
        pagination_row.append(InlineKeyboardButton("➡️", callback_data=f"stats_user_{target_pkid}_{page+1}_{target_username}"))
    
    keyboard = []
    if pagination_row:
        keyboard.append(pagination_row)
    
    keyboard.append([InlineKeyboardButton("🔙 返回声誉卡片", callback_data=f"back_to_rep_card_{target_pkid}_{target_username}")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def navigate_stats(update: Update, context: ContextTypes.DEFAULT_TYPE, target_pkid: int, page: int, target_username: str, direction: str):
    """用于统计页面导航（已合并到 show_user_statistics 中，此函数保留以防旧回调）。"""
    await show_user_statistics(update, context, target_pkid, page, target_username)
