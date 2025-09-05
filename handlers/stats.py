import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from math import ceil

from database import db_fetch_one, db_fetch_all

logger = logging.getLogger(__name__)

PAGE_SIZE = 5

async def user_stats_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, page: int = 1, origin: str = ""):
    query = update.callback_query
    
    user_info = await db_fetch_one("SELECT first_name, username FROM users WHERE pkid = $1", target_user_pkid)
    if not user_info:
        await query.answer("❌ 找不到该用户。", show_alert=True)
        return

    first_name = user_info.get('first_name')
    username = user_info.get('username')
    display_name = f"{first_name} (@{username})" if first_name and username else (username or first_name or f"用户 {target_user_pkid}")

    # --- 核心修正：修复KeyError ---
    # Get total distinct tags count
    total_tags_query = "SELECT COUNT(DISTINCT tag_id) as count FROM evaluations WHERE target_user_pkid = $1;"
    total_tags_record = await db_fetch_one(total_tags_query, target_user_pkid)
    # 使用 .get('count', 0) 来安全地获取值
    total_count = total_tags_record.get('count', 0) if total_tags_record else 0

    total_pages = ceil(total_count / PAGE_SIZE) if total_count > 0 else 1
    page = max(1, min(page, total_pages))
    offset = (page - 1) * PAGE_SIZE
    
    text = f"📊 **{display_name} 的声誉统计**\n\n收到的评价标签详情 (共 {total_count} 种):\n\n"
    
    tags_query = """
    SELECT t.name, t.type, COUNT(e.id) as count
    FROM evaluations e
    JOIN tags t ON e.tag_id = t.id
    WHERE e.target_user_pkid = $1
    GROUP BY t.id, t.name, t.type
    ORDER BY count DESC
    LIMIT $2 OFFSET $3;
    """
    tags_with_counts = await db_fetch_all(tags_query, target_user_pkid, PAGE_SIZE, offset)
    
    if not tags_with_counts:
        text += "_（暂无评价）_"
    else:
        for tag in tags_with_counts:
            icon = "👍" if tag['type'] == 'recommend' else "👎"
            text += f"- {icon} `{tag['name']}`: 被标记 {tag['count']} 次\n"
            
    # Pagination
    keyboard = []
    pagination_buttons = []
    if page > 1:
        pagination_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"stats_user_{target_user_pkid}_{page-1}_{origin}"))
    if page < total_pages:
        pagination_buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"stats_user_{target_user_pkid}_{page+1}_{origin}"))
    
    if pagination_buttons:
        keyboard.append(pagination_buttons)
        
    keyboard.append([InlineKeyboardButton("🔙 返回声誉卡片", callback_data=f"back_to_rep_card_{target_user_pkid}_{origin}")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
