import logging
from telegram import Update, User, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_cursor

logger = logging.getLogger(__name__)

async def register_user_if_not_exists(user: User):
    """
    确保一个用户存在于数据库中。
    修复: 直接使用传入的 User 对象，不再错误地检查 is_bot。
    """
    if not user: return
    # 机器人账号不记录
    if user.is_bot:
        return
        
    user_id = user.id
    username = user.username
    full_name = user.full_name
    
    with db_cursor() as cur:
        cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        if cur.fetchone() is None:
            cur.execute(
                "INSERT INTO users (id, username, full_name) VALUES (%s, %s, %s)",
                (user_id, username, full_name)
            )
            logger.info(f"新用户 {full_name} (@{username}) 已注册到数据库。")

async def handle_nomination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # (此函数内容与之前版本相同，无需修改)
    nominator = update.effective_user
    message = update.message
    
    await register_user_if_not_exists(nominator)

    mentioned_users = message.entities_to_users()
    if not mentioned_users:
        await message.reply_text("请在“查询”后 @ 一个用户。")
        return

    nominee = mentioned_users[0]
    await register_user_if_not_exists(nominee)
    
    if nominator.id == nominee.id:
        await message.reply_text("不能查询或评价自己哦。")
        return
    
    with db_cursor() as cur:
        cur.execute("SELECT * FROM users WHERE id = %s", (nominee.id,))
        nominee_data = cur.fetchone()
        
        cur.execute("""
            SELECT t.tag_name, COUNT(v.id) as vote_count
            FROM tags t
            JOIN votes v ON t.id = v.tag_id
            WHERE v.nominee_id = %s
            GROUP BY t.tag_name
            ORDER BY vote_count DESC
            LIMIT 5;
        """, (nominee.id,))
        top_tags = cur.fetchall()

    tags_str = ", ".join([f"{tag['tag_name']} ({tag['vote_count']})" for tag in top_tags]) if top_tags else "暂无"

    reply_text = (
        f"用户: {nominee.full_name} (@{nominee.username})\n"
        f"声望: {nominee_data['reputation']}\n"
        f"收到最多的评价: {tags_str}"
    )

    keyboard = [
        [
            InlineKeyboardButton("👍 推荐", callback_data=f"vote_up_{nominator.id}_{nominee.id}"),
            InlineKeyboardButton("👎 拉黑", callback_data=f"vote_down_{nominator.id}_{nominee.id}"),
        ],
        [
            InlineKeyboardButton("⭐ 添加到我的收藏", callback_data=f"fav_add_{nominator.id}_{nominee.id}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await message.reply_text(reply_text, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # (此函数内容与之前版本相同，无需修改)
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')
    action = data[0]

    if action == "vote":
        vote_type, nominator_id, nominee_id = data[1], int(data[2]), int(data[3])
        
        with db_cursor() as cur:
            cur.execute("SELECT id, tag_name, type FROM tags WHERE type = %s", ('recommend' if vote_type == 'up' else 'block',))
            tags = cur.fetchall()
        
        keyboard = []
        for tag in tags:
            keyboard.append([InlineKeyboardButton(tag['tag_name'], callback_data=f"tag_{tag['id']}_{nominator_id}_{nominee_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=f"请为 {'👍 推荐' if vote_type == 'up' else '👎 拉黑'} 选择一个标签:", reply_markup=reply_markup)

    elif action == "tag":
        tag_id, nominator_id, nominee_id = int(data[1]), int(data[2]), int(data[3])
        
        with db_cursor() as cur:
            cur.execute("SELECT 1 FROM votes WHERE nominator_id = %s AND nominee_id = %s AND tag_id = %s", (nominator_id, nominee_id, tag_id))
            if cur.fetchone():
                await context.bot.send_message(chat_id=query.from_user.id, text="你已经对该用户使用过这个标签了。")
                return

            cur.execute("INSERT INTO votes (nominator_id, nominee_id, tag_id) VALUES (%s, %s, %s)", (nominator_id, nominee_id, tag_id))
            
            cur.execute("SELECT type FROM tags WHERE id = %s", (tag_id,))
            tag_type = cur.fetchone()['type']
            rep_change = 1 if tag_type == 'recommend' else -1
            
            cur.execute("UPDATE users SET reputation = reputation + %s WHERE id = %s", (rep_change, nominee_id))
            
            cur.execute("SELECT tag_name FROM tags WHERE id = %s", (tag_id,))
            tag_name = cur.fetchone()['tag_name']

        await query.edit_message_text(text=f"感谢你的评价！你已为目标用户添加了 '{tag_name}' 标签。")
