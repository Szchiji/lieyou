from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from database import db_cursor
import logging
import math

logger = logging.getLogger(__name__)
ITEMS_PER_PAGE = 10

async def get_leaderboard_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """命令处理器，获取排行榜第一页。"""
    command = update.message.text.split()[0][1:]
    board_type = 'top' if 'top' in command else 'bottom'
    await send_leaderboard_page(update, context, board_type, 1)

async def leaderboard_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """按钮处理器，处理排行榜翻页。"""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('_')
    board_type = parts[1] # 'top' or 'bottom'
    page = int(parts[2])

    await send_leaderboard_page(update, context, board_type, page, is_callback=True)

async def send_leaderboard_page(update, context, board_type, page, is_callback=False):
    """发送指定页的排行榜。"""
    order_by = "upvotes DESC" if board_type == 'top' else "downvotes DESC"
    title = "🏆 红榜" if board_type == 'top' else "☠️ 黑榜"
    
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM targets")
        total_items = cur.fetchone()[0]
        total_pages = math.ceil(total_items / ITEMS_PER_PAGE)
        
        if page < 1: page = 1
        if page > total_pages: page = total_pages
        
        offset = (page - 1) * ITEMS_PER_PAGE
        
        cur.execute(
            f"SELECT * FROM targets ORDER BY {order_by} LIMIT %s OFFSET %s",
            (ITEMS_PER_PAGE, offset)
        )
        targets = cur.fetchall()

    if not targets:
        text = f"{title} - 目前是空的！"
    else:
        text = f"{title} - 第 {page} / {total_pages} 页\n\n"
        for i, target in enumerate(targets):
            rank = offset + i + 1
            text += f"{rank}. @{target['username']} - [👍{target['upvotes']} / 👎{target['downvotes']}]\n"
            
    keyboard = build_pagination_keyboard(board_type, page, total_pages)
    
    if is_callback:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')

def build_pagination_keyboard(board_type, current_page, total_pages):
    """构建翻页键盘。"""
    buttons = []
    row = []
    
    if current_page > 1:
        row.append(InlineKeyboardButton("« 首页", callback_data=f"leaderboard_{board_type}_1"))
        row.append(InlineKeyboardButton("‹ 上一页", callback_data=f"leaderboard_{board_type}_{current_page-1}"))
    
    if current_page < total_pages:
        row.append(InlineKeyboardButton("下一页 ›", callback_data=f"leaderboard_{board_type}_{current_page+1}"))
        row.append(InlineKeyboardButton("尾页 »", callback_data=f"leaderboard_{board_type}_{total_pages}"))
        
    if row:
        buttons.append(row)
        
    return InlineKeyboardMarkup(buttons)
 
