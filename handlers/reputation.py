import logging
from telegram import Update, User, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import MessageEntityType
from telegram.ext import ContextTypes
from database import db_cursor

logger = logging.getLogger(__name__)

# (register_user_if_not_exists 函数保持不变)
async def register_user_if_not_exists(user: User):
    if not user or user.is_bot: return
    async with db_cursor() as cur:
        existing_user = await cur.fetchrow("SELECT id, username, full_name FROM users WHERE id = $1", user.id)
        if not existing_user:
            await cur.execute("INSERT INTO users (id, username, full_name) VALUES ($1, $2, $3)", user.id, user.username, user.full_name)
        elif existing_user['username'] != user.username or existing_user['full_name'] != user.full_name:
            await cur.execute("UPDATE users SET username = $1, full_name = $2 WHERE id = $3", user.username, user.full_name, user.id)

async def handle_nomination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nominator = update.effective_user
    await register_user_if_not_exists(nominator)
    
    username_to_find = update.message.text.split('@')[1].strip()

    async with db_cursor() as cur:
        nominee_data = await cur.fetchrow("SELECT * FROM users WHERE username = $1", username_to_find)

    if not nominee_data:
        await update.message.reply_text(f"我的宇宙名录中没有找到用户 @{username_to_find} 的记录。")
        return

    nominee_id = nominee_data['id']
    if nominator.id == nominee_id:
        await update.message.reply_text("不能查询或评价自己哦。")
        return
    
    async with db_cursor() as cur:
        top_tags = await cur.fetch("""
            SELECT t.tag_name, COUNT(v.id) as vote_count FROM tags t
            JOIN votes v ON t.id = v.tag_id WHERE v.nominee_id = $1
            GROUP BY t.tag_name ORDER BY vote_count DESC LIMIT 5;
        """, nominee_id)

    tags_str = ", ".join([f"{t['tag_name']} ({t['vote_count']})" for t in top_tags]) if top_tags else "暂无"
    
    # 核心改造：显示推荐数和拉黑数
    reply_text = (f"用户: {nominee_data['full_name']} (@{nominee_data['username']})\n"
                  f"👍 推荐: {nominee_data['recommend_count']} 次\n"
                  f"👎 拉黑: {nominee_data['block_count']} 次\n"
                  f"收到最多的评价: {tags_str}")

    keyboard = [[InlineKeyboardButton("👍 推荐", callback_data=f"vote_up_{nominator.id}_{nominee_id}"),
                 InlineKeyboardButton("👎 拉黑", callback_data=f"vote_down_{nominator.id}_{nominee_id}")],
                [InlineKeyboardButton("⭐ 添加到我的收藏", callback_data=f"fav_add_{nominator.id}_{nominee_id}")]]
    await update.message.reply_text(reply_text, reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')
    action = data[0]

    if action == "vote":
        vote_type, nominator_id, nominee_id = data[1], int(data[2]), int(data[3])
        async with db_cursor() as cur:
            tags = await cur.fetch("SELECT id, tag_name FROM tags WHERE type = $1", 'recommend' if vote_type == 'up' else 'block')
        keyboard = [[InlineKeyboardButton(tag['tag_name'], callback_data=f"tag_{tag['id']}_{nominator_id}_{nominee_id}")] for tag in tags]
        await query.edit_message_text(text=f"请为 {'👍 推荐' if vote_type == 'up' else '👎 拉黑'} 选择一个标签:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "tag":
        tag_id, nominator_id, nominee_id = int(data[1]), int(data[2]), int(data[3])
        async with db_cursor() as cur:
            if await cur.fetchrow("SELECT 1 FROM votes WHERE nominator_id = $1 AND nominee_id = $2 AND tag_id = $3", nominator_id, nominee_id, tag_id):
                await context.bot.send_message(chat_id=query.from_user.id, text="你已经对该用户使用过这个标签了。")
                return

            await cur.execute("INSERT INTO votes (nominator_id, nominee_id, tag_id) VALUES ($1, $2, $3)", nominator_id, nominee_id, tag_id)
            tag_info = await cur.fetchrow("SELECT type, tag_name FROM tags WHERE id = $1", tag_id)
            
            # 核心改造：不再计算总分，而是分别更新计数字段
            if tag_info['type'] == 'recommend':
                await cur.execute("UPDATE users SET recommend_count = recommend_count + 1 WHERE id = $1", (nominee_id,))
            else: # 'block'
                await cur.execute("UPDATE users SET block_count = block_count + 1 WHERE id = $1", (nominee_id,))
            
        await query.edit_message_text(text=f"感谢你的评价！你已为目标用户添加了 '{tag_info['tag_name']}' 标签。")
