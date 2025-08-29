import logging
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_cursor

logger = logging.getLogger(__name__)
PAGE_SIZE = 5 # 为了在手机屏幕上获得更好的按钮列表体验，我们减少每页显示的数量

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int = 1):
    is_callback = update.callback_query is not None
    try:
        async with db_cursor() as cur:
            if board_type == 'top':
                title = "🏆 推荐榜 🏆"
                order_col = "recommend_count"
                count_col_name = "次推荐"
            else:
                title = "☠️ 拉黑榜 ☠️"
                order_col = "block_count"
                count_col_name = "次拉黑"
            
            total_record = await cur.fetchrow(f"SELECT COUNT(*) FROM reputation_profiles WHERE {order_col} > 0")
            profiles = await cur.fetch(f"SELECT username, {order_col} FROM reputation_profiles WHERE {order_col} > 0 ORDER BY {order_col} DESC, username ASC LIMIT {PAGE_SIZE} OFFSET {(page - 1) * PAGE_SIZE}")

        total_profiles = total_record['count']
        total_pages = math.ceil(total_profiles / PAGE_SIZE) if total_profiles > 0 else 1

        text = f"*{title}*\n(点击下方按钮直接查询)\n"

        keyboard = []
        if not profiles:
            text += "\n这个排行榜是空的。"
        else:
            # --- 核心革命：为排行榜上的每一个用户，都创建一个独立的、可直接查询的按钮 ---
            start_num = (page - 1) * PAGE_SIZE
            for i, p in enumerate(profiles):
                username = p['username']
                button_text = f"{i + start_num + 1}. @{username} - {p[order_col]} {count_col_name}"
                # 这个 callback_data 将被 all_button_handler 捕获，并触发 handle_favorite_button，
                # 最终调用 handle_nomination，形成完美的查询闭环。
                keyboard.append([
                    InlineKeyboardButton(button_text, callback_data=f"query_direct_{username}")
                ])

        # 添加翻页按钮
        page_row = []
        if page > 1: page_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"leaderboard_{board_type}_{page - 1}"))
        page_row.append(InlineKeyboardButton(f"第 {page}/{total_pages} 页", callback_data="leaderboard_noop"))
        if page < total_pages: page_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"leaderboard_{board_type}_{page + 1}"))
        if page_row: keyboard.append(page_row)
        
        reply_markup = InlineKeyboardMarkup(keyboard)

        # 切换回更稳定的 Markdown 模式
        if is_callback:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"生成排行榜时出错: {e}", exc_info=True)
        # ... (error handling)
        pass

async def get_top_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_leaderboard(update, context, board_type='top', page=1)

async def get_bottom_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_leaderboard(update, context, board_type='bottom', page=1)
