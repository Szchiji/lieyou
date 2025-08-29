import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction
from cachetools import TTLCache
from html import escape

logger = logging.getLogger(__name__)
cache = None
DEFAULT_TTL = 300

async def get_cache_ttl() -> int:
    try:
        async with db_transaction() as conn:
            setting = await conn.fetchrow("SELECT value FROM settings WHERE key = 'leaderboard_cache_ttl'")
        if setting and setting['value']:
            ttl = int(setting['value'])
            return ttl if ttl > 0 else DEFAULT_TTL
    except (ValueError, Exception) as e:
        logger.warning(f"无法从数据库获取有效的TTL，将使用默认值 {DEFAULT_TTL} 秒。错误: {e}")
    return DEFAULT_TTL

async def init_cache():
    global cache
    if cache is None:
        ttl = await get_cache_ttl()
        cache = TTLCache(maxsize=10, ttl=ttl)
        logger.info(f"英灵殿/深渊缓存已初始化，TTL: {ttl} 秒。")

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int = 1):
    if cache is None: await init_cache()
    
    is_refresh = update.callback_query and "_refresh" in update.callback_query.data
    if is_refresh:
        cache.clear()
        await update.callback_query.answer("🔄 镜像已刷新")

    cache_key = f"leaderboard_{board_type}"
    if cache_key in cache:
        all_profiles = cache[cache_key]
    else:
        order_col = "recommend_count" if board_type == "top" else "block_count"
        async with db_transaction() as conn:
            all_profiles = await conn.fetch(f"SELECT username, {order_col} as count FROM reputation_profiles WHERE {order_col} > 0 ORDER BY {order_col} DESC, username ASC")
        cache[cache_key] = all_profiles
    
    title = "🏆 英灵殿 (Hall of Heroes)" if board_type == "top" else "☠️ 放逐深渊 (The Abyss)"
    count_unit = "赞誉" if board_type == "top" else "警示"
    icon = "🥇🥈🥉"
    
    page_size = 10
    start_index = (page - 1) * page_size
    end_index = page * page_size
    profiles_on_page = all_profiles[start_index:end_index]
    
    if not profiles_on_page and page == 1:
        text = f"<b>{title}</b>\n\n此殿堂/深渊尚无一人，等待第一位被铭记或放逐的存在..."
    else:
        board_text = []
        rank_start = start_index + 1
        for i, profile in enumerate(profiles_on_page):
            rank = rank_start + i
            rank_icon = icon[rank-1] if rank <= 3 and page == 1 else f"<b>{rank}.</b>"
            board_text.append(f"{rank_icon} <code>@{escape(profile['username'])}</code> - {profile['count']} {count_unit}")
        text = f"<b>{title}</b>\n\n" + "\n".join(board_text)
        
    total_pages = (len(all_profiles) + page_size - 1) // page_size or 1
    
    page_row = []
    if page > 1: page_row.append(InlineKeyboardButton("⬅️ 上页", callback_data=f"leaderboard_{board_type}_{page-1}"))
    else: page_row.append(InlineKeyboardButton(" ", callback_data="leaderboard_noop"))
        
    page_row.append(InlineKeyboardButton(f"第 {page}/{total_pages} 页", callback_data="leaderboard_noop"))
    
    if page < total_pages: page_row.append(InlineKeyboardButton("下页 ➡️", callback_data=f"leaderboard_{board_type}_{page+1}"))
    else: page_row.append(InlineKeyboardButton(" ", callback_data="leaderboard_noop"))
        
    keyboard = [page_row, [InlineKeyboardButton("🔄 刷新镜像", callback_data=f"leaderboard_{board_type}_{page}_refresh")]]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        if is_refresh:
             # Prevent "Message is not modified" error after answering refresh
            try:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
            except BadRequest as e:
                if "Message is not modified" not in str(e): raise e
        else:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
