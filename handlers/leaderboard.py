import logging
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown
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
            else:
                title = "☠️ 拉黑榜 ☠️"
                order_col = "block_count"
                count_col_name = "次拉黑"
            
            total_record = await cur.fetchrow(f"SELECT COUNT(*) FROM reputation_profiles WHERE {order_col} > 0")
            profiles = await cur.fetch(f"SELECT username, {order_col} FROM reputation_profiles WHERE {order_col} > 0 ORDER BY {order_col} DESC, username ASC LIMIT {PAGE_SIZE} OFFSET {(page - 1) * PAGE_SIZE}")

        total_profiles = total_record['count']
        total_pages = math.ceil(total_profiles / PAGE_SIZE) if total_profiles > 0 else 1

        # --- 核心修复：对所有特殊字符进行转义 ---
        title_safe = escape_markdown(title, version=2)
        text = f"*{title_safe}*\n\(按符号排名\)\n\n" # 手动转义括号

        if not profiles:
            text += "这个排行榜是空的。"
        else:
            start_num = (page - 1) * PAGE_SIZE
            lines = []
            for i, p in enumerate(profiles):
                # 对用户名进行转义，以防用户名中包含特殊字符
                safe_username = escape_markdown(p['username'], version=2)
                line = f"{i + start_num + 1}\\. `@{safe_username}` \\- *{p[order_col]}* {count_col_name}"
                lines.append(line)
            text += "\n".join(lines)

        keyboard = []
        row = []
        if page > 1: row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"leaderboard_{board_type}_{page - 1}"))
        row.append(InlineKeyboardButton(f"第 {page}/{total_pages} 页", callback_data="leaderboard_noop"))
        if page < total_pages: row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"leaderboard_{board_type}_{page + 1}"))
        if row: keyboard.append(row)
        reply_markup = InlineKeyboardMarkup(keyboard)

        # 统一使用 MarkdownV2 模式发送
        if is_callback:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')

    except Exception as e:
        logger.error(f"生成排行榜时出错: {e}", exc_info=True)
        # 避免在出错时再次引发错误
        error_text = "生成排行榜时发生错误，请稍后再试。"
        if is_callback:
            await update.callback_query.edit_message_text(error_text)
        else:
            await update.message.reply_text(error_text)

async def get_top_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_leaderboard(update, context, board_type='top', page=1)

async def get_bottom_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_leaderboard(update, context, board_type='bottom', page=1)
