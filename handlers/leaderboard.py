import logging
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from database import db_transaction, update_user_activity
from html import escape

logger = logging.getLogger(__name__)

# 使用内存缓存优化排行榜查询性能
leaderboard_cache = {}
cache_timestamps = {}

def clear_leaderboard_cache():
    """清空排行榜缓存"""
    global leaderboard_cache, cache_timestamps
    leaderboard_cache = {}
    cache_timestamps = {}
    logger.info("🔄 排行榜缓存已清空")

async def get_cache_ttl():
    """获取缓存生存时间(秒)"""
    from database import db_transaction
    async with db_transaction() as conn:
        ttl_row = await conn.fetchrow("SELECT value FROM settings WHERE key = 'leaderboard_cache_ttl'")
    return int(ttl_row['value']) if ttl_row and ttl_row['value'] else 300

async def get_tag_leaderboard(tag_id: int, vote_type: str, page: int = 1, page_size: int = 10):
    """获取特定标签的排行榜数据，带缓存支持"""
    cache_key = f"{tag_id}_{vote_type}_{page}_{page_size}"
    
    # 检查缓存是否有效
    ttl = await get_cache_ttl()
    now = time.time()
    if cache_key in leaderboard_cache and now - cache_timestamps.get(cache_key, 0) < ttl:
        return leaderboard_cache[cache_key]
    
    # 缓存未命中，查询数据库
    async with db_transaction() as conn:
        # 首先获取标签信息
        tag = await conn.fetchrow("SELECT tag_name FROM tags WHERE id = $1 AND type = $2", tag_id, vote_type)
        if not tag:
            return None, None, []
        
        # 查询使用此标签的投票记录，按用户分组并计数
        query = """
            SELECT nominee_username, COUNT(*) as count
            FROM votes
            WHERE tag_id = $1
            GROUP BY nominee_username
            ORDER BY count DESC, nominee_username ASC
            LIMIT $2 OFFSET $3
        """
        start_idx = (page - 1) * page_size
        profiles_on_page = await conn.fetch(query, tag_id, page_size, start_idx)
        
        # 获取总记录数，用于计算总页数
        total_count = await conn.fetchval("""
            SELECT COUNT(DISTINCT nominee_username) 
            FROM votes 
            WHERE tag_id = $1
        """, tag_id)
    
    # 计算总页数
    total_pages = (total_count + page_size - 1) // page_size or 1
    
    # 缓存结果
    result = (tag['tag_name'], total_pages, profiles_on_page)
    leaderboard_cache[cache_key] = result
    cache_timestamps[cache_key] = now
    
    return result

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示排行榜页面"""
    query = update.callback_query
    parts = query.data.split('_')
    # 格式: leaderboard_{board_type}_{view_type}_{item_id}_{page}
    # view_type: 'tagselect' 或 'tag'
    board_type = parts[1]
    view_type = parts[2]
    
    # 更新用户活动
    await update_user_activity(query.from_user.id, query.from_user.username)
    
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
        # 查询所有标签以及每个标签的使用次数
        tags = await conn.fetch("""
            SELECT t.id, t.tag_name, COUNT(v.id) as usage_count
            FROM tags t
            LEFT JOIN votes v ON t.id = v.tag_id
            WHERE t.type = $1
            GROUP BY t.id, t.tag_name
            ORDER BY usage_count DESC, t.tag_name
        """, vote_type)

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
        count_text = f" ({tag['usage_count']})" if tag['usage_count'] > 0 else ""
        keyboard.append([InlineKeyboardButton(f"『{escape(tag['tag_name'])}』{count_text}", callback_data=f"leaderboard_{board_type}_tag_{tag['id']}_1")])

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
    page_size = 10
    
    # 从缓存或数据库获取排行榜数据
    tag_name, total_pages, profiles_on_page = await get_tag_leaderboard(tag_id, vote_type, page, page_size)
    
    if not tag_name:
        await update.callback_query.answer("❌ 错误：该箴言不存在或类型不匹配。", show_alert=True)
        return

    title_prefix = "🏆 英灵殿" if board_type == 'top' else "☠️ 放逐深渊"
    title = f"<b>{title_prefix}</b>\n箴言: 『{escape(tag_name)}』"
    count_unit = "次"
    icon = "🥇🥈🥉"
    
    if not profiles_on_page and page == 1:
        text = f"{title}\n\n尚无人因这句箴言而被铭记或警示。"
    else:
        board_text = []
        rank_start = (page - 1) * page_size + 1
        for i, profile in enumerate(profiles_on_page):
            rank = rank_start + i
            rank_icon = icon[rank-1] if rank <= 3 and page == 1 else f"<b>{rank}.</b>"
            board_text.append(f"{rank_icon} <code>@{escape(profile['nominee_username'])}</code> - {profile['count']} {count_unit}")
        text = f"{title}\n\n" + "\n".join(board_text)

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
