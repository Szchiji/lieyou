import logging
from telegram import Update, User, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import MessageEntityType
from telegram.helpers import escape_markdown  # <-- 核心修复：导入“转义”护身符
from telegram.ext import ContextTypes
from database import db_cursor

logger = logging.getLogger(__name__)

# (register_user_if_not_exists 函数保持不变)
async def register_user_if_not_exists(user: User):
    if not user or user.is_bot: return
    async with db_cursor() as cur:
        existing_user = await cur.fetchrow("SELECT id, username, full_name FROM users WHERE id = $1", user.id)
        full_name = user.full_name or " "
        username = user.username or " "
        if not existing_user:
            await cur.execute("INSERT INTO users (id, username, full_name, recommend_count, block_count, is_admin) VALUES ($1, $2, $3, 0, 0, FALSE)", user.id, username, full_name)
        elif existing_user['username'] != username or existing_user['full_name'] != full_name:
            await cur.execute("UPDATE users SET username = $1, full_name = $2 WHERE id = $3", username, full_name, user.id)

async def handle_nomination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nominator = update.effective_user
    await register_user_if_not_exists(nominator)
    
    try:
        message_text = update.message.text
        entities = update.message.entities
        username_to_find = ""
        for entity in entities:
            if entity.type == MessageEntityType.MENTION:
                username_to_find = message_text[entity.offset+1 : entity.offset+entity.length]
                break
        
        if not username_to_find:
            await update.message.reply_text("请使用 '查询 @username' 的格式。")
            return

        async with db_cursor() as cur:
            nominee_data = await cur.fetchrow("SELECT * FROM users WHERE LOWER(username) = LOWER($1)", username_to_find)

        if not nominee_data:
            safe_username = escape_markdown(username_to_find, version=2)
            await update.message.reply_text(f"我的宇宙名录中没有找到用户 @{safe_username} 的记录。")
            return

        nominee_id = nominee_data['id']
        if nominator.id == nominee_id:
            await update.message.reply_text("不能查询或评价自己哦。")
            return
        
        # --- 核心修复：在使用之前，为所有来自用户的文本佩戴上“护身符” ---
        safe_full_name = escape_markdown(nominee_data['full_name'], version=2)
        safe_username = escape_markdown(nominee_data['username'], version=2)

        async with db_cursor() as cur:
            top_tags = await cur.fetch("SELECT t.tag_name, COUNT(v.id) as vote_count FROM tags t JOIN votes v ON t.id = v.tag_id WHERE v.nominee_id = $1 GROUP BY t.tag_name ORDER BY vote_count DESC LIMIT 5;", nominee_id)

        tags_str = ", ".join([f"{escape_markdown(t['tag_name'], version=2)} ({t['vote_count']})" for t in top_tags]) if top_tags else "暂无"
        
        reply_text = (f"用户: {safe_full_name} \\(@{safe_username}\\)\n\n"
                      f"👍 *推荐*: {nominee_data.get('recommend_count', 0)} 次\n"
                      f"👎 *拉黑*: {nominee_data.get('block_count', 0)} 次\n\n"
                      f"*收到最多的评价*:\n{tags_str}")

        keyboard = [[InlineKeyboardButton("👍 推荐", callback_data=f"vote_up_{nominator.id}_{nominee_id}"),
                     InlineKeyboardButton("👎 拉黑", callback_data=f"vote_down_{nominator.id}_{nominee_id}")],
                    [InlineKeyboardButton("⭐ 添加到我的收藏", callback_data=f"fav_add_{nominator.id}_{nominee_id}")]]
        
        # --- 核心修复：使用更严格、更安全的 MarkdownV2 格式 ---
        await update.message.reply_text(reply_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='MarkdownV2')

    except Exception as e:
        logger.error(f"处理查询时出错: {e}", exc_info=True)
        await update.message.reply_text("处理查询时发生内部错误。")

# (button_handler 函数保持不变，因为我检查后发现它内部没有使用Markdown)
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split('_')
    action = data[0]
    try:
        if action == "vote":
            vote_type, nominator_id_str, nominee_id_str = data[1], data[2], data[3]
            tag_type = 'recommend' if vote_type == 'up' else 'block'
            async with db_cursor() as cur: tags = await cur.fetch("SELECT id, tag_name FROM tags WHERE type = $1", tag_type)
            if not tags:
                await query.edit_message_text(text=f"系统中还没有 '{'推荐' if tag_type == 'recommend' else '拉黑'}' 标签。")
                return
            keyboard = [[InlineKeyboardButton(tag['tag_name'], callback_data=f"tag_{tag['id']}_{nominator_id_str}_{nominee_id_str}")] for tag in tags]
            await query.edit_message_text(text=f"请为 {'👍 推荐' if vote_type == 'up' else '👎 拉黑'} 选择一个标签:", reply_markup=InlineKeyboardMarkup(keyboard))
        elif action == "tag":
            tag_id, nominator_id, nominee_id = int(data[1]), int(data[2]), int(data[3])
            async with db_cursor() as cur:
                result = await cur.execute("INSERT INTO votes (nominator_id, nominee_id, tag_id) VALUES ($1, $2, $3) ON CONFLICT (nominator_id, nominee_id, tag_id) DO NOTHING", nominator_id, nominee_id, tag_id)
                if "INSERT 0" in result:
                    await context.bot.send_message(chat_id=query.from_user.id, text="你已经对该用户使用过这个标签了。")
                    return
                tag_info = await cur.fetchrow("SELECT type, tag_name FROM tags WHERE id = $1", tag_id)
                if tag_info['type'] == 'recommend': await cur.execute("UPDATE users SET recommend_count = recommend_count + 1 WHERE id = $1", (nominee_id,))
                else: await cur.execute("UPDATE users SET block_count = block_count + 1 WHERE id = $1", (nominee_id,))
            await query.edit_message_text(text=f"感谢你的评价！你已为目标用户添加了 '{tag_info['tag_name']}' 标签。")
    except Exception as e:
        logger.error(f"处理按钮点击时出错: {e}", exc_info=True)
