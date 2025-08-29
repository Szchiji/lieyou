import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_cursor

logger = logging.getLogger(__name__)

async def my_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """私聊发送用户的收藏列表。"""
    user_id = update.effective_user.id
    try:
        async with db_cursor() as cur:
            favs = await cur.fetch("""
                SELECT u.full_name, u.username FROM favorites f
                JOIN users u ON f.favorite_user_id = u.id
                WHERE f.user_id = $1
            """, user_id)
        
        if not favs:
            text = "你的收藏夹是空的。"
        else:
            text = "你的收藏夹:\n" + "\n".join([f"- {f['full_name']} (@{f['username']})" for f in favs])
        
        await context.bot.send_message(chat_id=user_id, text=text)
        if update.message.chat.type != 'private':
            await update.message.reply_text("已将你的收藏夹私聊发送给你。")
    except Exception as e:
        logger.error(f"发送收藏夹时出错: {e}")
        await update.message.reply_text("获取收藏夹时出错，请确保你已私聊启动我。")

async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示用户自己的声望和标签。"""
    user_id = update.effective_user.id
    async with db_cursor() as cur:
        user_data = await cur.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        tags = await cur.fetch("""
            SELECT t.tag_name, COUNT(v.id) as count FROM votes v
            JOIN tags t ON v.tag_id = t.id
            WHERE v.nominee_id = $1 GROUP BY t.tag_name ORDER BY count DESC
        """, user_id)
    
    if not user_data:
        await update.message.reply_text("似乎还没有你的记录，请先在群里发言。")
        return

    tags_str = "\n".join([f"- {tag['tag_name']} ({tag['count']})" for tag in tags]) if tags else "暂无"
    
    text = (f"我的档案:\n"
            f"声望: {user_data['reputation']}\n\n"
            f"收到的评价标签:\n{tags_str}")
            
    await update.message.reply_text(text)

async def handle_favorite_button(query, context):
    """处理收藏按钮点击。"""
    _, action, nominator_id, nominee_id = query.data.split('_')
    nominator_id, nominee_id = int(nominator_id), int(nominee_id)

    if query.from_user.id != nominator_id:
        await query.answer("这不是你的操作按钮。", show_alert=True)
        return
    
    async with db_cursor() as cur:
        if action == 'add':
            await cur.execute("""
                INSERT INTO favorites (user_id, favorite_user_id) VALUES ($1, $2)
                ON CONFLICT (user_id, favorite_user_id) DO NOTHING
            """, nominator_id, nominee_id)
            await query.answer("已添加到收藏夹！", show_alert=True)
        elif action == 'remove':
            await cur.execute("DELETE FROM favorites WHERE user_id = $1 AND favorite_user_id = $2", nominator_id, nominee_id)
            await query.answer("已从收藏夹移除。", show_alert=True)
