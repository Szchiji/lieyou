import logging
from telegram import Update, User, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import MessageEntityType # 确保导入 MessageEntityType
from telegram.ext import ContextTypes
from database import db_cursor

logger = logging.getLogger(__name__)

async def register_user_if_not_exists(user: User):
    """如果用户不存在则注册，并更新其用户名和全名。"""
    if not user or user.is_bot: return
    async with db_cursor() as cur:
        existing_user = await cur.fetchrow("SELECT id, username, full_name FROM users WHERE id = $1", user.id)
        # 确保 full_name 和 username 不为 None
        full_name = user.full_name or " "
        username = user.username or " "
        
        if not existing_user:
            await cur.execute("INSERT INTO users (id, username, full_name) VALUES ($1, $2, $3)", user.id, username, full_name)
        elif existing_user['username'] != username or existing_user['full_name'] != full_name:
            await cur.execute("UPDATE users SET username = $1, full_name = $2 WHERE id = $3", username, full_name, user.id)

async def handle_nomination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理查询 @username 的逻辑。"""
    nominator = update.effective_user
    await register_user_if_not_exists(nominator)
    
    try:
        # --- 核心修复：使用正确的语法来提取 @username ---
        message_text = update.message.text
        entities = update.message.entities
        username_to_find = ""

        for entity in entities:
            if entity.type == MessageEntityType.MENTION:
                offset = entity.offset
                length = entity.length
                username_to_find = message_text[offset+1 : offset+length]
                break
        # --- 修复结束 ---
        
        if not username_to_find:
            await update.message.reply_text("请使用 '查询 @username' 的格式，并确保 @username 是一个有效的用户。")
            return

        async with db_cursor() as cur:
            # 确保在查询时也处理大小写不敏感的情况
            nominee_data = await cur.fetchrow("SELECT * FROM users WHERE LOWER(username) = LOWER($1)", username_to_find)

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
        
        reply_text = (f"用户: {nominee_data['full_name']} (@{nominee_data['username']})\n"
                      f"声望: {nominee_data['reputation']}\n"
                      f"收到最多的评价: {tags_str}")

        keyboard = [[InlineKeyboardButton("👍 推荐", callback_data=f"vote_up_{nominator.id}_{nominee_id}"),
                     InlineKeyboardButton("👎 拉黑", callback_data=f"vote_down_{nominator.id}_{nominee_id}")],
                    [InlineKeyboardButton("⭐ 添加到我的收藏", callback_data=f"fav_add_{nominator.id}_{nominee_id}")]]
        await update.message.reply_text(reply_text, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"处理查询时出错: {e}", exc_info=True) # 添加 exc_info=True 以记录更详细的错误
        await update.message.reply_text("处理查询时发生内部错误。")

# (button_handler 函数保持不变)
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理所有与评价相关的按钮点击。"""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')
    action = data[0]

    try:
        if action == "vote":
            vote_type, nominator_id, nominee_id = data[1], int(data[2]), int(data[3])
            tag_type = 'recommend' if vote_type == 'up' else 'block'
            
            async with db_cursor() as cur:
                tags = await cur.fetch("SELECT id, tag_name FROM tags WHERE type = $1", tag_type)
            
            if not tags:
                await query.edit_message_text(text=f"系统中还没有可用的 '{'推荐' if tag_type == 'recommend' else '拉黑'}' 标签。请先让管理员添加。")
                return

            keyboard = [[InlineKeyboardButton(tag['tag_name'], callback_data=f"tag_{tag['id']}_{nominator_id}_{nominee_id}")] for tag in tags]
            await query.edit_message_text(text=f"请为 {'👍 推荐' if vote_type == 'up' else '👎 拉黑'} 选择一个标签:", reply_markup=InlineKeyboardMarkup(keyboard))

        elif action == "tag":
            tag_id, nominator_id, nominee_id = int(data[1]), int(data[2]), int(data[3])
            async with db_cursor() as cur:
                # 使用 ON CONFLICT (nominator_id, nominee_id, tag_id) DO NOTHING 避免重复投票
                result = await cur.execute("""
                    INSERT INTO votes (nominator_id, nominee_id, tag_id) VALUES ($1, $2, $3)
                    ON CONFLICT (nominator_id, nominee_id, tag_id) DO NOTHING
                """, nominator_id, nominee_id, tag_id)

                if result == "INSERT 0":
                    await context.bot.send_message(chat_id=query.from_user.id, text="你已经对该用户使用过这个标签了。")
                    return

                tag_info = await cur.fetchrow("SELECT type, tag_name FROM tags WHERE id = $1", tag_id)
                
                change = 1 if tag_info['type'] == 'recommend' else -1
                await cur.execute("UPDATE users SET reputation = reputation + $1 WHERE id = $2", change, nominee_id)
            
            await query.edit_message_text(text=f"感谢你的评价！你已为目标用户添加了 '{tag_info['tag_name']}' 标签。")
    except Exception as e:
        logger.error(f"处理按钮点击时出错: {e}", exc_info=True)
        try:
            await query.edit_message_text("处理评价时发生内部错误。")
        except: pass
