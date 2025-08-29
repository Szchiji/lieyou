from telegram import Update
from telegram.ext import ContextTypes
from psycopg2.extras import DictCursor

from database import get_conn, put_conn
from handlers.decorators import restricted_to_group

@restricted_to_group
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示声望最高的头狼榜。"""
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT username, reputation FROM users ORDER BY reputation DESC LIMIT 10")
            top_users = cur.fetchall()

            board_text = "🏆 **头狼榜** 🏆\n\n"
            if not top_users:
                board_text += "狼群正在集结，暂无排名..."
            else:
                for i, user in enumerate(top_users, 1):
                    rank_icon = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"**{i}.**"
                    board_text += f"{rank_icon} @{user['username']} - {user['reputation']} 声望\n"
            
            await update.message.reply_text(board_text, parse_mode='Markdown')
    finally:
        put_conn(conn)
