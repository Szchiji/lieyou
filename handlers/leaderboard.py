import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from database import db_transaction
from html import escape

logger = logging.getLogger(__name__)
cache = None

def clear_leaderboard_cache():
    """公开的函数，用于从外部模块清除排行榜缓存。"""
    global cache
    if cache is not None:
        cache.clear()

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split('_')
    # 新格式: leaderboard_{board_type}_{view_type}_{item_id}_{page}
    # view_type: 'tagselect' 或 'tag'
    # item_id: 对于 view_type='tag'，这是 tag_id
    board_type = parts[1]
    view_type = parts[2]
    
    if view_type == 'tagselect':
        page = int(parts[3])
        await show_tag_selection(update, board_type, page)
    elif view_type == 'tag':
        tag_id = int(parts[3])
        page = int(parts[4])
        await show_tag_leaderboard(update, board_type, tag_id, page)

async def show_tag_selection(update: Update, board_type: str, page: int = 1):
    """显示箴言选择列表"""
    vote_type = 'recommend' if board_type == 'top' else 'block'
    title = "🏆 英灵殿" if board_type == 'top' else "☠️ 放逐深渊"
    
    async with db_transaction() as conn:
        tags = await conn.fetch("SELECT id, tag_name FROM tags WHERE type = $1 ORDER BY tag_name", vote_type)

    if not tags:
        text = f"<b>{title}</b>\n\n尚未锻造任何相关的箴言。"
        keyboard = [[InlineKeyboardButton("⬅️ 返回", callback_data="back_to_help")]]
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return

    text = f"<b>{title}</b>\n\n请选择一句箴言，以窥探其专属的时代群像："
    page_size = 8
    start_index = (page - 1) * page_size
    end_index = page * page_size
    tags_on_page = tags[start_index:end_index]
    
    keyboard = []
    for tag in tags_on_page:
        keyboard.append([InlineKeyboardButton(f"『{escape(tag['tag_name'])}』", callback_data=f"leaderboard_{board_type}_tag_{tag['id']}_1")])

    total_pages = (len(tags) + page_size - 1) // page_size or 1
    page_row = []
    if page > 1: page_row.append(InlineKeyboardButton("⬅️ 上页", callback_data=f"leaderboard_{board_type}_tagselect_{page-1}"))
    else: page_row.append(InlineKeyboardButton(" ", callback_data="noop"))
    page_row.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages: page_row.append(InlineKeyboardButton("下页 ➡️", callback_data=f"leaderboard_{board_type}_tagselect_{page+1}"))
    else: page_row.append(InlineKeyboardButton(" ", callback_data="noop"))
    
    keyboard.append(page_row)
    keyboard.append([InlineKeyboardButton("🌍 返回凡界", callback_data="back_to_help")])
    
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


async def show_tag_leaderboard(update: Update, board_type: str, tag_id: int, page: int = 1):
    """显示特定箴言的排行榜"""
    vote_type = 'recommend' if board_type == 'top' else 'block'
    
    async with db_transaction() as conn:
        tag = await conn.fetchrow("SELECT tag_name FROM tags WHERE id = $1 AND type = $2", tag_id, vote_type)
        if not tag:
            await update.callback_query.answer("❌ 错误：该箴言不存在或类型不匹配。", show_alert=True)
            return

        query = """
            SELECT nominee_username, COUNT(*) as count
            FROM votes
            WHERE tag_id = $1
            GROUP BY nominee_username
            ORDER BY count DESC, nominee_username ASC
        """
        all_profiles = await conn.fetch(query, tag_id)

    title_prefix = "🏆 英灵殿" if board_type == 'top' else "☠️ 放逐深渊"
    title = f"<b>{title_prefix}</b>\n箴言: 『{escape(tag['tag_name'])}』"
    count_unit = "次"
    icon = "🥇🥈🥉"
    
    page_size = 10
    start_index = (page - 1) * page_size
    end_index = page * page_size
    profiles_on_page = all_profiles[start_index:end_index]

    if not profiles_on_page and page == 1:
        text = f"{title}\n\n尚无人因这句箴言而被铭记或警示。"
    else:
        board_text = []
        rank_start = start_index + 1
        for i, profile in enumerate(profiles_on_page):
            rank = rank_start + i
            rank_icon = icon[rank-1] if rank <= 3 and page == 1 else f"<b>{rank}.</b>"
            board_text.append(f"{rank_icon} <code>@{escape(profile['nominee_username'])}</code> - {profile['count']} {count_unit}")
        text = f"{title}\n\n" + "\n".join(board_text)

    total_pages = (len(all_profiles) + page_size - 1) // page_size or 1
    
    page_row = []
    if page > 1: page_row.append(InlineKeyboardButton("⬅️ 上页", callback_data=f"leaderboard_{board_type}_tag_{tag_id}_{page-1}"))
    else: page_row.append(InlineKeyboardButton(" ", callback_data="noop"))
    page_row.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages: page_row.append(InlineKeyboardButton("下页 ➡️", callback_data=f"leaderboard_{board_type}_tag_{tag_id}_{page+1}"))
    else: page_row.append(InlineKeyboardButton(" ", callback_data="noop"))

    keyboard = [page_row, [InlineKeyboardButton("⬅️ 返回箴言选择", callback_data=f"leaderboard_{board_type}_tagselect_1")]]
    
    try:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.error(f"编辑箴言排行榜时出错: {e}")
