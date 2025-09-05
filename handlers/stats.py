import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from database import db_fetch_all, db_fetch_one

logger = logging.getLogger(__name__)

async def user_stats_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, page: int = 1, origin: str = ""):
    query = update.callback_query
    per_page = 5
    offset = (page - 1) * per_page
    
    user_info = await db_fetch_one("SELECT first_name, username FROM users WHERE pkid = $1", target_user_pkid)
    first_name = user_info.get('first_name')
    username = user_info.get('username')
    if first_name and first_name != username:
        display_name = f"{first_name} (@{username})" if username else first_name
    elif username:
        display_name = f"@{username}"
    else:
        display_name = f"用户 {target_user_pkid}"

    votes = await db_fetch_all(
        """
        SELECT t.name, t.type, COUNT(v.id) as count
        FROM votes v JOIN tags t ON v.tag_id = t.id
        WHERE v.target_user_pkid = $1
        GROUP BY t.name, t.type
        ORDER BY count DESC
        LIMIT $2 OFFSET $3
        """, target_user_pkid, per_page, offset)

    total_votes = await db_fetch_one("SELECT COUNT(DISTINCT tag_id) FROM votes WHERE target_user_pkid = $1", target_user_pkid)
    total_count = total_votes[0] if total_votes else 0
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    
    text = f"📊 **详细统计: {display_name} (第 {page}/{total_pages} 页)**\n\n"
    if not votes:
        text += "该用户还没有收到任何评价。"
    else:
        for vote in votes:
            icon = "👍" if vote['type'] == 'recommend' else '👎'
            text += f"{icon} `{vote['name']}`: {vote['count']} 次\n"
            
    keyboard = []
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"stats_user_{target_user_pkid}_{page-1}_{origin}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"stats_user_{target_user_pkid}_{page+1}_{origin}"))
    if nav_row:
        keyboard.append(nav_row)
        
    # 终极修复：确保返回按钮的回调数据携带来源
    keyboard.append([InlineKeyboardButton("🔙 返回声誉卡片", callback_data=f"back_to_rep_card_{target_user_pkid}_{origin}")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
