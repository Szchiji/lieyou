import logging
import math
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction # <--- 注意：我们现在导入的是 db_transaction

logger = logging.getLogger(__name__)
PAGE_SIZE = 5
leaderboard_cache = {} # 引入一个简单的内存缓存

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int = 1):
    """显示排行榜，引入缓存机制以优化性能并遵守世界法则。"""
    is_callback = update.callback_query is not None
    
    try:
        # --- 法则执行：首先获取世界法则 ---
        async with db_transaction() as conn:
            ttl_row = await conn.fetchrow("SELECT value FROM settings WHERE key = 'leaderboard_cache_ttl'")
        cache_ttl = int(ttl_row['value']) if ttl_row else 300 # 如果没设置，默认为300秒
        
        cache_key = f"{board_type}_{page}"
        current_time = time.time()

        # --- 法则执行：检查缓存是否有效 ---
        if cache_key in leaderboard_cache and current_time - leaderboard_cache[cache_key]['timestamp'] < cache_ttl:
            cached_data = leaderboard_cache[cache_key]['data']
            logger.info(f"命中排行榜缓存: {cache_key}")
            if is_callback:
                await update.callback_query.edit_message_text(**cached_data)
            else:
                await update.message.reply_text(**cached_data)
            return
        
        logger.info(f"未命中排行榜缓存，正在从数据库生成: {cache_key}")
        # --- 灵魂修复：使用事务从数据库获取真实数据 ---
        async with db_transaction() as conn:
            title = "🏆 推荐榜 🏆" if board_type == 'top' else "☠️ 拉黑榜 ☠️"
            order_col = "recommend_count" if board_type == 'top' else "block_count"
            count_col_name = "次推荐" if board_type == 'top' else "次拉黑"
            
            total_record = await conn.fetchrow(f"SELECT COUNT(*) FROM reputation_profiles WHERE {order_col} > 0")
            profiles = await conn.fetch(f"SELECT username, {order_col} FROM reputation_profiles WHERE {order_col} > 0 ORDER BY {order_col} DESC, username ASC LIMIT {PAGE_SIZE} OFFSET {(page - 1) * PAGE_SIZE}")

        total_profiles = total_record['count']
        total_pages = math.ceil(total_profiles / PAGE_SIZE) if total_profiles > 0 else 1
        text = f"*{title}*\n(点击下方按钮直接查询)\n"
        keyboard = []

        if not profiles:
            text += "\n这个排行榜是空的。"
        else:
            start_num = (page - 1) * PAGE_SIZE
            for i, p in enumerate(profiles):
                username = p['username']
                button_text = f"{i + start_num + 1}. @{username} - {p[order_col]} {count_col_name}"
                callback_data = f"query_direct_{username}_back_leaderboard_{board_type}_{page}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

        page_row = []
        if page > 1: page_row.append(InlineKeyboardButton("⬅️ 上页", callback_data=f"leaderboard_{board_type}_{page - 1}"))
        page_row.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="leaderboard_noop"))
        if page < total_pages: page_row.append(InlineKeyboardButton("下页 ➡️", callback_data=f"leaderboard_{board_type}_{page + 1}"))
        if page_row: keyboard.append(page_row)
        
        keyboard.append([InlineKeyboardButton("⬅️ 返回主菜单", callback_data="back_to_help")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        # --- 法则执行：将新生成的数据存入缓存 ---
        message_data = {'text': text, 'reply_markup': reply_markup, 'parse_mode': 'Markdown'}
        leaderboard_cache[cache_key] = {'timestamp': current_time, 'data': message_data}
        
        # 发送消息
        if is_callback:
            await update.callback_query.edit_message_text(**message_data)
        else:
            await update.message.reply_text(**message_data)

    except Exception as e:
        logger.error(f"生成排行榜时出错: {e}", exc_info=True)
        pass

async def get_top_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_leaderboard(update, context, board_type='top', page=1)

async def get_bottom_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_leaderboard(update, context, board_type='bottom', page=1)
