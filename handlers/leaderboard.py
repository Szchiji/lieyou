import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction
from cachetools import TTLCache
from html import escape

logger = logging.getLogger(__name__)

# 使用带有 TTL (Time-To-Live) 的缓存
# cache = TTLCache(maxsize=10, ttl=300) # 默认5分钟缓存
# 我们将从数据库读取缓存时间
async def get_cache_ttl() -> int:
    async with db_transaction() as conn:
        setting = await conn.fetchrow("SELECT value FROM settings WHERE key = 'leaderboard_cache_ttl'")
    return int(setting['value']) if setting else 300

cache = None

async def init_cache():
    global cache
    if cache is None:
        ttl = await get_cache_ttl()
        cache = TTLCache(maxsize=10, ttl=ttl)
        logger.info(f"排行榜缓存已初始化，TTL: {ttl} 秒。")


async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int = 1):
    if cache is None: await init_cache() # 确保缓存已初始化
    
    cache_key = f"leaderboard_{board_type}"
    
    if cache_key in cache:
        all_profiles = cache[cache_key]
        logger.info(f"排行榜缓存命中: {cache_key}")
    else:
        logger.info(f"排行榜缓存未命中，从数据库查询: {cache_key}")
        order_col = "recommend_count" if board_type == "top" else "block_count"
        async with db_transaction() as conn:
            all_profiles = await conn.fetch(
                f"SELECT username, {order_col} as count FROM reputation_profiles WHERE {order_col} > 0 ORDER BY {order_col} DESC, username ASC"
            )
        cache[cache_key] = all_profiles
    
    title = "🏆 红榜 (Top 10)" if board_type == "top" else "☠️ 黑榜 (Top 10)"
    page_size = 10
    start_index = (page - 1) * page_size
    end_index = page * page_size
    
    profiles_on_page = all_profiles[start_index:end_index]
    
    if not profiles_on_page and page == 1:
        text = f"{title}\n\n榜单上空空如也。"
    else:
        board_text = []
        rank_start = start_index + 1
        for i, profile in enumerate(profiles_on_page):
            rank = rank_start + i
            board_text.append(f"{rank}. @{escape(profile['username'])} - {profile['count']} 票")
        text = f"{title}\n\n" + "\n".join(board_text)
        
    # 构建翻页按钮
    total_pages = (len(all_profiles) + page_size - 1) // page_size
    keyboard = []
    page_row = []
    if page > 1:
        page_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"leaderboard_{board_type}_{page-1}"))
    else:
        page_row.append(InlineKeyboardButton(" ", callback_data="leaderboard_noop_0")) # 占位
        
    page_row.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="leaderboard_noop_0")) # 显示页码
    
    if page < total_pages:
        page_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"leaderboard_{board_type}_{page+1}"))
    else:
        page_row.append(InlineKeyboardButton(" ", callback_data="leaderboard_noop_0")) # 占位
        
    keyboard.append(page_row)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # --- 核心改造：在原消息上编辑，而不是发送新消息 ---
    if update.callback_query:
        # 如果是按钮触发的，就在原消息上编辑
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        # 如果是命令触发的，就发送新消息
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
