import logging
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown  # <-- 核心修复：导入“转义”护身符
from database import db_cursor

logger = logging.getLogger(__name__)

PAGE_SIZE = 10

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int = 1):
    is_callback = update.callback_query is not None
    try:
        async with db_cursor() as cur:
            if board_type == 'top':
                title = "🏆 推荐榜 🏆"
                order_col = "recommend_count"
                count_col_name = "次推荐"
            else: # 'bottom'
                title = "☠️ 拉黑榜 ☠️"
                order_col = "block_count"
                count_col_name = "次拉黑"
            
            total_users_record = await cur.fetchrow(f"SELECT COUNT(*) FROM users WHERE {order_col} > 0")
            users = await cur.fetch(f"SELECT full_name, username, {order_col} FROM users WHERE {order_col} > 0 ORDER BY {order_col} DESC, id ASC LIMIT {PAGE_SIZE} OFFSET {(page - 1) * PAGE_SIZE}")

        total_users = total_users_record['count']
        total_pages = math.ceil(total_users / PAGE_SIZE) if total_users > 0 else 1

        text = f"*{title}*\n\n"
        if not users:
            text += "这个排行榜是空的。"
        else:
            start_num = (page - 1) * PAGE_SIZE
            user_lines = []
            for i, u in enumerate(users):
                # --- 核心修复：为排行榜上的每个名字都佩戴上“护身符” ---
                safe_name = escape_markdown(u['full_name'], version=2)
                safe_username = escape_markdown(u['username'], version=2)
                line = f"{i + start_num + 1}\\. {safe_name} \\(@{safe_username}\\) \\- *{u[order_col]}* {count_col_name}"
                user_lines.append(line)
            text += "\n".join(user_lines)

        keyboard = []
        row = []
        if page > 1: row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"leaderboard_{board_type}_{page - 1}"))
        row.append(InlineKeyboardButton(f"第 {page}/{total_pages} 页", callback_data="leaderboard_noop"))
        if page < total_pages: row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"leaderboard_{board_type}_{page + 1}"))
        if row: keyboard.append(row)
        reply_markup = InlineKeyboardMarkup(keyboard)

        # --- 核心修复：使用更安全的 MarkdownV2 格式 ---
        if is_callback:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')

    except Exception as e:
        logger.error(f"生成排行榜时出错: {e}", exc_info=True)

# (get_top_board 和 get_bottom_board 函数保持不变)
async def get_top_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_leaderboard(update, context, board_type='top', page=1)

async def get_bottom_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_leaderboard(update, context, board_type='bottom', page=1)
