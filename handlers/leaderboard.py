from telegram import Update
from telegram.ext import ContextTypes
from database import db_cursor

async def get_top_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示推荐榜"""
    async with db_cursor() as cur:
        users = await cur.fetch("""
            SELECT full_name, username, recommend_count 
            FROM users 
            WHERE username != 'GroupAnonymousBot' AND recommend_count > 0
            ORDER BY recommend_count DESC, block_count ASC
            LIMIT 10
        """)
    
    text = "🏆 **推荐榜** 🏆\n(收到推荐最多的用户)\n\n"
    if not users:
        text += "目前还没有人获得推荐。"
    else:
        text += "\n".join([f"{i+1}. {u['full_name']} (@{u['username']}) - {u['recommend_count']} 次推荐" for i, u in enumerate(users)])
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def get_bottom_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示拉黑榜"""
    async with db_cursor() as cur:
        users = await cur.fetch("""
            SELECT full_name, username, block_count 
            FROM users 
            WHERE username != 'GroupAnonymousBot' AND block_count > 0
            ORDER BY block_count DESC, recommend_count ASC
            LIMIT 10
        """)

    text = "☠️ **拉黑榜** ☠️\n(收到拉黑最多的用户)\n\n"
    if not users:
        text += "目前还没有人被拉黑。"
    else:
        text += "\n".join([f"{i+1}. {u['full_name']} (@{u['username']}) - {u['block_count']} 次拉黑" for i, u in enumerate(users)])

    await update.message.reply_text(text, parse_mode='Markdown')

# leaderboard_button_handler 不再需要，因为我们不再提供刷新按钮
