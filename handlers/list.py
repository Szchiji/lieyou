import math
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from psycopg2.extras import DictCursor

from database import get_conn, put_conn
from constants import CALLBACK_LIST_PREFIX, TYPE_HUNT, TYPE_TRAP

ITEMS_PER_PAGE = 5

def format_time_ago(dt: datetime):
    if not dt: return "未知"
    now = datetime.utcnow().replace(tzinfo=None)
    dt_naive = dt.replace(tzinfo=None)
    diff = now - dt_naive
    seconds = diff.total_seconds()
    if seconds < 60: return "刚刚"
    minutes = seconds / 60
    if minutes < 60: return f"{int(minutes)}分钟前"
    hours = minutes / 60
    if hours < 24: return f"{int(hours)}小时前"
    days = hours / 24
    return f"{int(days)}天前"

async def list_prey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    page = 1
    sort_by = 'time'

    if query:
        await query.answer()
        try:
            parts = query.data.split('_')
            page = int(parts[2])
            sort_by = parts[4]
        except (IndexError, ValueError): pass
    
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(f"SELECT COUNT(id) FROM resources WHERE (SELECT COUNT(*) FROM feedback WHERE resource_id = resources.id AND type = '{TYPE_HUNT}') > 0")
            total_items = cur.fetchone()[0]
            total_pages = math.ceil(total_items / ITEMS_PER_PAGE) if total_items > 0 else 1
            page = max(1, min(page, total_pages))

            order_clause = "ORDER BY latest_activity DESC"
            if sort_by == 'hot':
                order_clause = "ORDER BY hunt_count DESC, trap_count ASC"

            offset = (page - 1) * ITEMS_PER_PAGE
            
            cur.execute(f"""
                SELECT 
                    r.id, r.content, r.sharer_username,
                    (SELECT COUNT(*) FROM feedback WHERE resource_id = r.id AND type = '{TYPE_HUNT}') as hunt_count,
                    (SELECT COUNT(*) FROM feedback WHERE resource_id = r.id AND type = '{TYPE_TRAP}') as trap_count,
                    (SELECT MAX(created_at) FROM feedback WHERE resource_id = r.id) as latest_activity
                FROM resources r
                WHERE (SELECT COUNT(*) FROM feedback WHERE resource_id = r.id AND type = '{TYPE_HUNT}') > 0
                {order_clause}
                LIMIT %s OFFSET %s;
            """, (ITEMS_PER_PAGE, offset))
            
            items = cur.fetchall()

            list_text = f"🐺 **狼群的狩猎名录** (第 {page}/{total_pages} 页)\n\n"
            if not items:
                list_text += "名录空空如也，等待第一位伟大的猎手！"
            else:
                for i, item in enumerate(items, 1):
                    desc = item['content'] or "[无文字描述]"
                    desc = desc[:30] + "..." if len(desc) > 30 else desc
                    list_text += (
                        f"**{i + offset}. {desc}**\n"
                        f"  - 分享者: @{item['sharer_username']}\n"
                        f"  - 认可度: 👍 {item['hunt_count']} / 👎 {item['trap_count']}\n"
                        f"  - 最近活动: {format_time_ago(item['latest_activity'])}\n\n"
                    )
            
            keyboard = []
            sort_buttons = [
                InlineKeyboardButton("🔄 按热度" if sort_by != 'hot' else "【热度】", callback_data=f"{CALLBACK_LIST_PREFIX}{page}_sort_hot"),
                InlineKeyboardButton("🔄 按时间" if sort_by != 'time' else "【时间】", callback_data=f"{CALLBACK_LIST_PREFIX}{page}_sort_time")
            ]
            keyboard.append(sort_buttons)

            page_buttons = []
            if page > 1: page_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"{CALLBACK_LIST_PREFIX}{page-1}_sort_{sort_by}"))
            if page < total_pages: page_buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"{CALLBACK_LIST_PREFIX}{page+1}_sort_{sort_by}"))
            if page_buttons: keyboard.append(page_buttons)

            reply_markup = InlineKeyboardMarkup(keyboard)

            if query:
                await query.edit_message_text(list_text, reply_markup=reply_markup, parse_mode='Markdown')
            else:
                await update.message.reply_text(list_text, reply_markup=reply_markup, parse_mode='Markdown')
    finally:
        put_conn(conn)
