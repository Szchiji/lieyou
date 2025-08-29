import logging
from telegram import Update, User, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import MessageEntityType
from telegram.ext import ContextTypes
from database import db_cursor

logger = logging.getLogger(__name__)

async def register_user_if_not_exists(user: User):
    """确保一个用户存在于数据库中。"""
    if not user or user.is_bot:
        return
        
    user_id = user.id
    username = user.username
    full_name = user.full_name
    
    with db_cursor() as cur:
        # 检查用户是否已存在
        cur.execute("SELECT id, username, full_name FROM users WHERE id = %s", (user_id,))
        existing_user = cur.fetchone()
        
        if not existing_user:
            # 用户不存在，插入新用户
            cur.execute(
                "INSERT INTO users (id, username, full_name) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (user_id, username, full_name)
            )
            logger.info(f"新用户 {full_name} (@{username}) 已注册到数据库。")
        elif existing_user['username'] != username or existing_user['full_name'] != full_name:
            # 用户存在，但信息已更改，进行更新
            cur.execute(
                "UPDATE users SET username = %s, full_name = %s WHERE id = %s",
                (username, full_name, user_id)
            )
            logger.info(f"用户 {user_id} 的信息已更新为 @{username} ({full_name})。")


async def handle_nomination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理“查询 @username”命令。
    全新逻辑: 直接从消息中提取 @username 字符串, 然后在我们的全局数据库中搜索。
    """
    nominator = update.effective_user
    message = update.message
    
    # 确保操作者本人已在数据库中注册
    await register_user_if_not_exists(nominator)

    # 1. 从消息中解析出 @username 字符串
    mentioned_users_map = message.parse_entities(types=[MessageEntityType.MENTION])
    if not mentioned_users_map:
        await message.reply_text("请在“查询”后 @ 一个用户。")
        return

    # 提取第一个被 @ 的用户名 (例如: "@someuser")
    first_entity = list(mentioned_users_map.keys())[0]
    username_to_find = mentioned_users_map[first_entity]
    
    # 去掉开头的 '@' 符号
    username_to_find_clean = username_to_find.lstrip('@')

    # 2. 在我们的全局 `users` 表中搜索这个 username
    with db_cursor() as cur:
        cur.execute("SELECT * FROM users WHERE username = %s", (username_to_find_clean,))
        nominee_data = cur.fetchone()

    # 3. 根据搜索结果进行回应
    if not nominee_data:
        # 如果在我们的全局数据库中都找不到这个用户
        await message.reply_text(
            f"我在我的宇宙名录中没有找到用户 {username_to_find} 的记录。\n\n"
            "这通常意味着他从没有和我在任何地方互动过。\n"
            "请让他先与我互动一次（例如在任何群里说句话，或私聊我 /start），我才能将他载入史册。"
        )
        return

    # 4. 如果找到了用户，展示他的信息和评价按钮
    nominee_id = nominee_data['id']
    nominee_full_name = nominee_data['full_name']
    nominee_username = nominee_data['username']
    
    if nominator.id == nominee_id:
        await message.reply_text("不能查询或评价自己哦。")
        return
    
    with db_cursor() as cur:
        cur.execute("""
            SELECT t.tag_name, COUNT(v.id) as vote_count
            FROM tags t
            JOIN votes v ON t.id = v.tag_id
            WHERE v.nominee_id = %s
            GROUP BY t.tag_name
            ORDER BY vote_count DESC
            LIMIT 5;
        """, (nominee_id,))
        top_tags = cur.fetchall()

    tags_str = ", ".join([f"{tag['tag_name']} ({tag['vote_count']})" for tag in top_tags]) if top_tags else "暂无"

    reply_text = (
        f"用户: {nominee_full_name} (@{nominee_username})\n"
        f"声望: {nominee_data['reputation']}\n"
        f"收到最多的评价: {tags_str}"
    )

    keyboard = [
        [
            InlineKeyboardButton("👍 推荐", callback_data=f"vote_up_{nominator.id}_{nominee_id}"),
            InlineKeyboardButton("👎 拉黑", callback_data=f"vote_down_{nominator.id}_{nominee_id}"),
        ],
        [
            InlineKeyboardButton("⭐ 添加到我的收藏", callback_data=f"fav_add_{nominator.id}_{nominee_id}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await message.reply_text(reply_text, reply_markup=reply_markup)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理所有回调按钮（此函数无需修改）"""
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
