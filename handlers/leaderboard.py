import logging
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_cursor

logger = logging.getLogger(__name__)
PAGE_SIZE = 5

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int = 1):
    is_callback = update.callback_query is not None
    try:
        async with db_cursor() as cur:
            title = "🏆 推荐榜 🏆" if board_type == 'top' else "☠️ 拉黑榜 ☠️"
            order_col = "recommend_count" if board_type == 'top' else "block_count"
            count_col_name = "次推荐" if board_type == 'top' else "次拉黑"
            
            total_record = await cur.fetchrow(f"SELECT COUNT(*) FROM reputation_profiles WHERE {order_col} > 0")
            profiles = await cur.fetch(f"SELECT username, {order_col} FROM reputation_profiles WHERE {order_col} > 0 ORDER BY {order_col} DESC, username ASC LIMIT {PAGE_SIZE} OFFSET {(page - 1) * PAGE_SIZE}")

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
                # --- 核心改造：在查询按钮中嵌入返回路径信息 ---
                # "query_direct_USERNAME_back_leaderboard_top_1"
                callback_data = f"query_direct_{username}_back_leaderboard_{board_type}_{page}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

        page_row = []
        if page > 1: page_row.append(InlineKeyboardButton("⬅️ 上页", callback_data=f"leaderboard_{board_type}_{page - 1}"))
        page_row.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="leaderboard_noop"))
        if page < total_pages: page_row.append(InlineKeyboardButton("下页 ➡️", callback_data=f"leaderboard_{board_type}_{page + 1}"))
        if page_row: keyboard.append(page_row)
        
        # --- 核心改造：添加“返回主菜单”按钮 ---
        keyboard.append([InlineKeyboardButton("⬅️ 返回主菜单", callback_data="back_to_help")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)

        if is_callback:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"生成排行榜时出错: {e}", exc_info=True)
        pass

# ... (get_top_board, get_bottom_board 保持不变) ...
async def get_top_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_leaderboard(update, context, board_type='top', page=1)

async def get_bottom_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_leaderboard(update, context, board_type='bottom', page=1)
