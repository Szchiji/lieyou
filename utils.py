import asyncpg
import os
import datetime
from telegram import Update

PG_URL = os.environ.get("DATABASE_URL", "postgresql://user:password@localhost:5432/daka")

# 数据库连接池
pool = None

async def get_db():
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(dsn=PG_URL)
    return pool

# 判断管理员
async def is_admin(user_id, chat_id=None):
    db = await get_db()
    sql = "SELECT 1 FROM admins WHERE user_id=$1"
    if chat_id:
        sql += " AND chat_id=$2"
        row = await db.fetchrow(sql, user_id, chat_id)
    else:
        row = await db.fetchrow(sql, user_id)
    return row is not None

def today_str():
    return datetime.date.today().strftime("%Y-%m-%d")

# 快捷装饰器：检测管理员权限
def admin_required(func):
    async def wrapper(update: Update, context):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id if update.effective_chat else None
        if not await is_admin(user_id, chat_id):
            await update.message.reply_text("⚠️ 只有管理员可用此功能。")
            return
        return await func(update, context)
    return wrapper
