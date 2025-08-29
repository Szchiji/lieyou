import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction
from cachetools import TTLCache
from html import escape

logger = logging.getLogger(__name__)
cache = None
DEFAULT_TTL = 300 # 设定一个不可动摇的默认值

async def get_cache_ttl() -> int:
    """
    获取缓存TTL。
    - 优先从数据库读取。
    - 如果读取失败、值为非数字或小于0，则使用默认值。
    """
    try:
        async with db_transaction() as conn:
            setting = await conn.fetchrow("SELECT value FROM settings WHERE key = 'leaderboard_cache_ttl'")
        
        if setting and setting['value']:
            ttl = int(setting['value'])
            # 确保TTL是正数，否则使用默认值
            return ttl if ttl > 0 else DEFAULT_TTL
    except (ValueError, Exception) as e:
        # 如果转换整数失败或数据库查询出错，记录警告并返回默认值
        logger.warning(f"无法从数据库获取有效的TTL，将使用默认值 {DEFAULT_TTL} 秒。错误: {e}")
    
    return DEFAULT_TTL # 最终的保障

async def init_cache():
    """初始化排行榜缓存，使用绝对可靠的TTL值。"""
    global cache
    if cache is None:
        ttl = await get_cache_ttl()
        cache = TTLCache(maxsize=10, ttl=ttl)
        logger.info(f"排行榜缓存已初始化，TTL: {ttl} 秒。")

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int = 1):
    if cache is None: await init_cache()
    
    # 在刷新时，清除缓存以获取最新数据
    if update.callback_query and update.callback_query.data.endswith("_refresh"):
        cache.clear()
        await update.callback_query.answer("🔄 已刷新")
    
    cache_key = f"leaderboard_{board_type}"
    if cache_key in cache:
        all_profiles = cache[cache_key]
    else:
        order_col = "recommend_count" if board_type == "top" else "block_count"
        async with db_transaction() as conn:
            all_profiles = await conn.fetch(f"SELECT username, {order_col} as count FROM reputation_profiles WHERE {order_col} > 0 ORDER BY {order_col} DESC, username ASC")
        cache[cache_key] = all_profiles
    
    title = "🏆 红榜 · Top Recommended" if board_type == "top" else "☠️ 黑榜 · Top Blocked"
    icon = "🥇🥈🥉"
    
    page_size = 10
    start_index = (page - 1) * page_size
    end_index = page * page_size
    profiles_on_page = all_profiles[start_index:end_index]
    
    if not profiles_on_page and page == 1:
        text = f"<b>{title}</b>\n\n榜单上空空如也，等待第一位英雄/恶人。 虚位以待..."
    else:
        board_text = []
        rank_start = start_index + 1
        for i, profile in enumerate(profiles_on_page):
            rank = rank_start + i
            rank_icon = icon[rank-1] if rank <= 3 and page == 1 else f"<b>{rank}.</b>"
            board_text.append(f"{rank_icon} <code>@{escape(profile['username'])}</code> - {profile['count']} 票")
        text = f"<b>{title}</b>\n\n" + "\n".join(board_text)
        
    total_pages = (len(all_profiles) + page_size - 1) // page_size
    if total_pages == 0: total_pages = 1
    
    page_row = []
    if page > 1: page_row.append(InlineKeyboardButton("⬅️ 上页", callback_data=f"leaderboard_{board_type}_{page-1}"))
    else: page_row.append(InlineKeyboardButton(" ", callback_data="leaderboard_noop"))
        
    page_row.append(InlineKeyboardButton(f"第 {page}/{total_pages} 页", callback_data="leaderboard_noop"))
    
    if page < total_pages: page_row.append(InlineKeyboardButton("下页 ➡️", callback_data=f"leaderboard_{board_type}_{page+1}"))
    else: page_row.append(InlineKeyboardButton(" ", callback_data="leaderboard_noop"))
        
    keyboard = [page_row, [InlineKeyboardButton("🔄 刷新", callback_data=f"leaderboard_{board_type}_{page}_refresh")]]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
