from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_cursor

async def my_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with db_cursor() as cur:
        favs = await cur.fetch("""
            SELECT u.id, u.full_name, u.username FROM favorites f 
            JOIN users u ON f.favorite_user_id = u.id
            WHERE f.user_id = $1
        """, user_id)
    if not favs:
        await update.message.reply_text("你的收藏夹是空的。")
        return

    text = "你的收藏夹:\n"
    keyboard = []
    for fav in favs:
        text += f"- {fav['full_name']} (@{fav['username']})\n"
        keyboard.append([InlineKeyboardButton(f"移除 {fav['full_name']}", callback_data=f"fav_remove_{user_id}_{fav['id']}")])
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with db_cursor() as cur:
        user_data = await cur.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        tags = await cur.fetch("""
            SELECT t.tag_name, COUNT(v.id) as count FROM votes v
            JOIN tags t ON v.tag_id = t.id
            WHERE v.nominee_id = $1 GROUP BY t.tag_name
        """, user_id)
    
    tags_str = "\n".join([f"- {tag['tag_name']} ({tag['count']})" for tag in tags]) or "暂无"
    text = f"我的档案:\n声望: {user_data['reputation']}\n收到的评价:\n{tags_str}"
    await update.message.reply_text(text)

async def handle_favorite_button(query, context):
    action, user_id, fav_user_id = query.data.split('_')
    user_id, fav_user_id = int(user_id), int(fav_user_id)

    async with db_cursor() as cur:
        if action == "fav_add":
            await cur.execute("INSERT INTO favorites (user_id, favorite_user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", user_id, fav_user_id)
            await query.answer("已添加到收藏夹！")
        elif action == "fav_remove":
            await cur.execute("DELETE FROM favorites WHERE user_id = $1 AND favorite_user_id = $2", user_id, fav_user_id)
            await query.answer("已从收藏夹移除！")
            # 刷新收藏夹消息
            favs = await cur.fetch("""
                SELECT u.id, u.full_name, u.username FROM favorites f 
                JOIN users u ON f.favorite_user_id = u.id WHERE f.user_id = $1
            """, user_id)
            if not favs:
                await query.edit_message_text("你的收藏夹是空的。")
                return
            text = "你的收藏夹:\n" + "\n".join([f"- {f['full_name']} (@{f['username']})" for f in favs])
            keyboard = [[InlineKeyboardButton(f"移除 {f['full_name']}", callback_data=f"fav_remove_{user_id}_{f['id']}")] for f in favs]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
