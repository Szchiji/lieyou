from telegram import Update
from telegram.ext import ContextTypes
from psycopg2.extras import DictCursor

from database import get_conn, put_conn, get_user_rank
from constants import TYPE_HUNT, TYPE_TRAP

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示用户自己的或被回复用户的个人档案。"""
    target_user = None
    if update.effective_message.reply_to_message:
        target_user = update.effective_message.reply_to_message.from_user
    else:
        target_user = update.effective_user

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (target_user.id,))
            user_data = cur.fetchone()

            if not user_data:
                await update.message.reply_text(f"@{target_user.username} 还没有在狼群中留下足迹。")
                return

            rep = user_data['reputation']
            rank = get_user_rank(rep)

            # 统计狩猎记录
            cur.execute(f"SELECT COUNT(*) FROM feedback WHERE marker_id = %s AND type = '{TYPE_HUNT}'", (target_user.id,))
            hunts_made = cur.fetchone()[0]
            cur.execute(f"SELECT COUNT(*) FROM feedback WHERE marker_id = %s AND type = '{TYPE_TRAP}'", (target_user.id,))
            traps_marked = cur.fetchone()[0]

            # 统计战利品
            cur.execute(f"SELECT COUNT(f.id) FROM feedback f JOIN resources r ON f.resource_id = r.id WHERE r.sharer_id = %s AND f.type = '{TYPE_HUNT}'", (target_user.id,))
            hunted_count = cur.fetchone()[0]
            cur.execute(f"SELECT COUNT(f.id) FROM feedback f JOIN resources r ON f.resource_id = r.id WHERE r.sharer_id = %s AND f.type = '{TYPE_TRAP}'", (target_user.id,))
            trapped_count = cur.fetchone()[0]

            profile_text = (
                f"👤 **@{user_data['username']} 的档案**\n\n"
                f"**头衔**: {rank}\n"
                f"**声望**: {rep}\n\n"
                f"--- **狩猎记录** ---\n"
                f"  - 成功狩猎: {hunts_made} 次\n"
                f"  - 标记陷阱: {traps_marked} 次\n\n"
                f"--- **战利品统计** ---\n"
                f"  - 分享被认可: {hunted_count} 次\n"
                f"  - 分享被警告: {trapped_count} 次"
            )
            await update.message.reply_text(profile_text, parse_mode='Markdown')
    finally:
        put_conn(conn)
# ... (其他导入) ...
from handlers.decorators import restricted_to_group

@restricted_to_group
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (函数内部代码保持不变) ...
