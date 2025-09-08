import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import get_leaderboard_page

PAGE_SIZE = 10

def _format_row(rank_index: int, user: dict) -> str:
    medal = "🥇" if rank_index == 1 else "🥈" if rank_index == 2 else "🥉" if rank_index == 3 else f"{rank_index}."
    name = user.get('username')
    if name:
        display = f"@{name}"
    else:
        display = user.get('first_name') or "用户"
    return f"{medal} {display}  分:{user['reputation_score']} (+{user['recommendations']}/-{user['warnings']})"

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_leaderboard(update, context, page=1, edit=False)

async def leaderboard_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data  # lb_page_2
    parts = data.split('_')
    if len(parts) == 3 and parts[0] == 'lb' and parts[1] == 'page':
        page = int(parts[2])
        await _send_leaderboard(update, context, page=page, edit=True)

async def _send_leaderboard(update_or_query, context, page: int, edit: bool):
    rows, total = await get_leaderboard_page(page, PAGE_SIZE)
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    start_rank = (page - 1) * PAGE_SIZE + 1

    text = f"📊 信誉排行榜 (第 {page}/{total_pages} 页)\n\n"
    if not rows:
        text += "暂无数据"
    else:
        for i, user in enumerate(rows):
            text += _format_row(start_rank + i, user) + "\n"

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"lb_page_{page-1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"lb_page_{page+1}"))

    keyboard = [nav_row] if nav_row else []
    markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    if edit and update_or_query.callback_query:
        await update_or_query.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=markup
        )
    else:
        if update_or_query.message:
            await update_or_query.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)
        else:
            await update_or_query.callback_query.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)
