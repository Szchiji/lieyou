import logging
from telegram import Update, User, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import MessageEntityType
from telegram.ext import ContextTypes
from database import db_cursor

logger = logging.getLogger(__name__)

async def register_user_if_not_exists(user: User):
    if not user or user.is_bot: return
    
    async with db_cursor() as cur:
        existing_user = await cur.fetchrow("SELECT id, username, full_name FROM users WHERE id = $1", user.id)
        
        if not existing_user:
            await cur.execute("INSERT INTO users (id, username, full_name) VALUES ($1, $2, $3)", user.id, user.username, user.full_name)
            logger.info(f"新用户 {user.full_name} (@{user.username}) 已注册。")
        elif existing_user['username'] != user.username or existing_user['full_name'] != user.full_name:
            await cur.execute("UPDATE users SET username = $1, full_name = $2 WHERE id = $3", user.username, user.full_name, user.id)
            logger.info(f"用户 {user.id} 的信息已更新。")

async def handle_nomination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nominator = update.effective_user
    message = update.message
    await register_user_if_not_exists(nominator)

    mentioned_users_map = message.parse_entities(types=[MessageEntityType.MENTION])
    if not mentioned_users_map:
        await message.reply_text("请在“查询”后 @ 一个用户。")
        return

    first_entity = list(mentioned_users_map.keys())[0]
    username_to_find = mentioned_users_map[first_entity].lstrip('@')

    async with db_cursor() as cur:
        nominee_data = await cur.fetchrow("SELECT * FROM users WHERE username = $1", username_to_find)

    if not nominee_data:
        await message.reply_text(f"我的宇宙名录中没有找到用户 @{username_to_find} 的记录。请让他先与我互动一次。")
        return

    nominee_id = nominee_data['id']
    if nominator.id == nominee_id:
        await message.reply_text("不能查询或评价自己哦。")
        return
    
    async with db_cursor() as cur:
        top_tags = await cur.fetch("""
            SELECT t.tag_name, COUNT(v.id) as vote_count FROM tags t
            JOIN votes v ON t.id = v.tag_id WHERE v.nominee_id = $1
            GROUP BY t.tag_name ORDER BY vote_count DESC LIMIT 5;
        """, nominee_id)

    tags_str = ", ".join([f"{tag['tag_name']} ({tag['vote_count']})" for tag in top_tags]) if top_tags else "暂无"
    reply_text = (f"用户: {nominee_data['full_name']} (@{nominee_data['username']})\n"
                  f"声望: {nominee_data['reputation']}\n"
                  f"收到最多的评价: {tags_str}")

    keyboard = [[InlineKeyboardButton("👍 推荐", callback_data=f"vote_up_{nominator.id}_{nominee_id}"),
                 InlineKeyboardButton("👎 拉黑", callback_data=f"vote_down_{nominator.id}_{nominee_id}")],
                [InlineKeyboardButton("⭐ 添加到我的收藏", callback_data=f"fav_add_{nominator.id}_{nominee_id}")]]
    await message.reply_text(reply_text, reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')
    action, nominator_id, nominee_id = data[0], int(data[-2]), int(data[-1])

    if action == "vote":
        vote_type = data[1]
        async with db_cursor() as cur:
            tags = await cur.fetch("SELECT id, tag_name FROM tags WHERE type = $1", 'recommend' if vote_type == 'up' else 'block')
        keyboard = [[InlineKeyboardButton(tag['tag_name'], callback_data=f"tag_{tag['id']}_{nominator_id}_{nominee_id}")] for tag in tags]
        await query.edit_message_text(text=f"请为 {'👍 推荐' if vote_type == 'up' else '👎 拉黑'} 选择一个标签:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "tag":
        tag_id = int(data[1])
        async with db_cursor() as cur:
            if await cur.fetchrow("SELECT 1 FROM votes WHERE nominator_id = $1 AND nominee_id = $2 AND tag_id = $3", nominator_id, nominee_id, tag_id):
                await context.bot.send_message(chat_id=query.from_user.id, text="你已经对该用户使用过这个标签了。")
                return

            await cur.execute("INSERT INTO votes (nominator_id, nominee_id, tag_id) VALUES ($1, $2, $3)", nominator_id, nominee_id, tag_id)
            tag_info = await cur.fetchrow("SELECT type, tag_name FROM tags WHERE id = $1", tag_id)
            rep_change = 1 if tag_info['type'] == 'recommend' else -1
            await cur.execute("UPDATE users SET reputation = reputation + $1 WHERE id = $2", rep_change, nominee_id)
            
        await query.edit_message_text(text=f"感谢你的评价！你已为目标用户添加了 '{tag_info['tag_name']}' 标签。")
