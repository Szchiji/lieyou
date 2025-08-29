import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction
from cachetools import TTLCache
from html import escape

logger = logging.getLogger(__name__)
cache = None

async def get_cache_ttl() -> int:
    async with db_transaction() as conn:
        setting = await conn.fetchrow("SELECT value FROM settings WHERE key = 'leaderboard_cache_ttl'")
    return int(setting['value']) if setting else 300

async def init_cache():
    global cache
    if cache is None:
        ttl = await get_cache_ttl()
        cache = TTLCache(maxsize=10, ttl=ttl)
        logger.info(f"排行榜缓存已初始化，TTL: {ttl} 秒。")

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int = 1):
    if cache is None: await init_cache()
    
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
    else: page_row.append(InlineKeyboardButton(" ", callback_data="leaderboard_noop_0"))
        
    page_row.append(InlineKeyboardButton(f"第 {page}/{total_pages} 页", callback_data="leaderboard_noop_0"))
    
    if page < total_pages: page_row.append(InlineKeyboardButton("下页 ➡️", callback_data=f"leaderboard_{board_type}_{page+1}"))
    else: page_row.append(InlineKeyboardButton(" ", callback_data="leaderboard_noop_0"))
        
    keyboard = [page_row, [InlineKeyboardButton("🔄 刷新", callback_data=f"leaderboard_{board_type}_{page}")]]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
