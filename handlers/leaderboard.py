from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown
from database import db_cursor
import logging
import math

logger = logging.getLogger(__name__)
ITEMS_PER_PAGE = 10

async def get_top_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_leaderboard_page(update, context, 'top', 1)

async def get_bottom_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_leaderboard_page(update, context, 'bottom', 1)

async def leaderboard_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split('_')
    board_type = parts[1]
    page = int(parts[2])
    await send_leaderboard_page(update, context, board_type, page, is_callback=True)

async def send_leaderboard_page(update, context, board_type, page, is_callback=False):
    order_by_column = "upvotes" if board_type == 'top' else "downvotes"
    title = "🏆 红榜" if board_type == 'top' else "☠️ 黑榜"
    
    with db_cursor() as cur:
        count_condition = f"WHERE {order_by_column} > 0"
        cur.execute(f"SELECT COUNT(*) FROM targets {count_condition}")
        total_items = cur.fetchone()[0]
        total_pages = math.ceil(total_items / ITEMS_PER_PAGE) if total_items > 0 else 1
        page = max(1, min(page, total_pages))
        offset = (page - 1) * ITEMS_PER_PAGE
        
        cur.execute(
            f"SELECT * FROM targets {count_condition} ORDER BY {order_by_column} DESC LIMIT %s OFFSET %s",
            (ITEMS_PER_PAGE, offset)
        )
        targets = cur.fetchall()

    if not targets:
        text = f"*{escape_markdown(title, version=2)}* \- 目前是空的！"
    else:
        text = f"*{escape_markdown(title, version=2)} \- 第 {page} / {total_pages} 页*\n\n"
        for i, target in enumerate(targets):
            rank = offset + i + 1
            safe_username = escape_markdown(target['username'] or 'N/A', version=2)
            # 修正: 对所有可能包含特殊字符的部分进行转义
            text += f"{rank}\\. @{safe_username} \\- \\[👍{target['upvotes']} / 👎{target['downvotes']}\\]\n"
            
    keyboard = build_pagination_keyboard(board_type, page, total_pages)
    effective_update = update.callback_query if is_callback else update
    
    try:
        if is_callback:
            if effective_update.message.text != text:
                await effective_update.edit_message_text(text, reply_markup=keyboard, parse_mode='MarkdownV2')
        else:
            await effective_update.message.reply_text(text, reply_markup=keyboard, parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"发送排行榜时出错: {e}")
        # 如果出错，发送一个不带格式的纯文本版本
        plain_text = text.replace('*', '').replace('\\', '')
        await effective_update.message.reply_text(plain_text, reply_markup=keyboard)


def build_pagination_keyboard(board_type, current_page, total_pages):
    if total_pages <= 1: return None
    row = []
    if current_page > 1:
        row.extend([
            InlineKeyboardButton("« 首页", callback_data=f"leaderboard_{board_type}_1"),
            InlineKeyboardButton("‹ 上一页", callback_data=f"leaderboard_{board_type}_{current_page-1}")
        ])
    if current_page < total_pages:
        row.extend([
            InlineKeyboardButton("下一页 ›", callback_data=f"leaderboard_{board_type}_{current_page+1}"),
            InlineKeyboardButton("尾页 »", callback_data=f"leaderboard_{board_type}_{total_pages}")
        ])
    return InlineKeyboardMarkup([row]) if row else None
