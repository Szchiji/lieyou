import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_cursor

logger = logging.getLogger(__name__)

async def register_admin_if_not_exists(user_id: int):
    async with db_cursor() as cur:
        await cur.execute("INSERT INTO users (id) VALUES ($1) ON CONFLICT DO NOTHING", user_id)

async def handle_nomination(
    update: Update, 
    context: ContextTypes.DEFAULT_TYPE, 
    direct_username: str | None = None, 
    from_favorites: bool = False
):
    nominator_id = update.effective_user.id
    await register_admin_if_not_exists(nominator_id)

    nominee_username = None
    if direct_username:
        nominee_username = direct_username
    else:
        # 这里的 update.message 可能是 None，需要做安全检查
        if update.message:
            match = re.search(r'@(\S+)', update.message.text)
            if match:
                nominee_username = match.group(1)

    if not nominee_username:
        # 如果是按钮触发的，静默处理；如果是消息触发的，则回复
        if update.callback_query: await update.callback_query.answer()
        elif update.message: await update.message.reply_text("请使用 '查询 @任意符号' 的格式。")
        return

    try:
        async with db_cursor() as cur:
            await cur.execute("INSERT INTO reputation_profiles (username) VALUES ($1) ON CONFLICT DO NOTHING", nominee_username)
            profile_data = await cur.fetchrow("SELECT * FROM reputation_profiles WHERE username = $1", nominee_username)
            top_tags = await cur.fetch("""
                SELECT t.tag_name, COUNT(v.id) as vote_count FROM tags t
                JOIN votes v ON t.id = v.tag_id WHERE v.nominee_username = $1
                GROUP BY t.tag_name ORDER BY vote_count DESC LIMIT 5;
            """, nominee_username)

        tags_str = ", ".join([f"{t['tag_name']} ({t['vote_count']})" for t in top_tags]) if top_tags else "暂无"
        
        # --- 核心优化说明 ---
        # 在档案卡这个“最终页面”，`@username` 使用可点击复制的 ` ` 格式是最佳选择。
        # 因为用户到达这里后，最可能的操作是“复制这个名字去别处分享”，而不是“再次点击查询自己”。
        # 这是一种符合直觉的、终点式的交互设计。
        reply_text = (f"符号: `@{nominee_username}`\n\n"
                      f"👍 *推荐*: {profile_data.get('recommend_count', 0)} 次\n"
                      f"👎 *拉黑*: {profile_data.get('block_count', 0)} 次\n\n"
                      f"*收到最多的评价*:\n{tags_str}")

        keyboard = [
            [InlineKeyboardButton("👍 推荐", callback_data=f"vote_up_{nominator_id}_{nominee_username}"),
             InlineKeyboardButton("👎 拉黑", callback_data=f"vote_down_{nominator_id}_{nominee_username}")],
            [InlineKeyboardButton("⭐ 添加到我的收藏", callback_data=f"fav_add_{nominator_id}_{nominee_username}")]
        ]

        if from_favorites:
            keyboard.append([InlineKeyboardButton("⬅️ 返回收藏夹", callback_data="back_to_favs")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 统一使用更稳定的 Markdown 模式
        if update.callback_query:
            await update.callback_query.edit_message_text(reply_text, reply_markup=reply_markup, parse_mode='Markdown')
        elif update.message:
            await update.message.reply_text(reply_text, reply_markup=reply_markup, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"处理符号查询时出错: {e}", exc_info=True)
        pass

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理档案卡上的“推荐”和“拉黑”按钮，引导用户选择标签。"""
    query = update.callback_query
    data = query.data.split('_')
    action = data[0]
    try:
        if action == "vote":
            vote_type, nominator_id_str, nominee_username = data[1], data[2], "_".join(data[3:])
            tag_type = 'recommend' if vote_type == 'up' else 'block'
            async with db_cursor() as cur:
                tags = await cur.fetch("SELECT id, tag_name FROM tags WHERE type = $1", tag_type)
            if not tags:
                await query.edit_message_text(text=f"系统中还没有可用的 '{'推荐' if tag_type == 'recommend' else '拉黑'}' 标签。请先让管理员添加。")
                return
            keyboard = [[InlineKeyboardButton(tag['tag_name'], callback_data=f"tag_{tag['id']}_{nominator_id_str}_{nominee_username}")] for tag in tags]
            await query.edit_message_text(text=f"请为 `@{nominee_username}` 选择一个标签:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        elif action == "tag":
            tag_id, nominator_id_str, nominee_username = int(data[1]), data[2], "_".join(data[3:])
            nominator_id = int(nominator_id_str)
            async with db_cursor() as cur:
                result = await cur.execute("INSERT INTO votes (nominator_id, nominee_username, tag_id) VALUES ($1, $2, $3) ON CONFLICT (nominator_id, nominee_username, tag_id) DO NOTHING", nominator_id, nominee_username, tag_id)
                if "INSERT 0" in result:
                    await context.bot.send_message(chat_id=query.from_user.id, text=f"你已经对 `@{nominee_username}` 使用过这个标签了。", parse_mode='Markdown')
                    return
                tag_info = await cur.fetchrow("SELECT type, tag_name FROM tags WHERE id = $1", tag_id)
                if tag_info['type'] == 'recommend':
                    await cur.execute("UPDATE reputation_profiles SET recommend_count = recommend_count + 1 WHERE username = $1", (nominee_username,))
                else:
                    await cur.execute("UPDATE reputation_profiles SET block_count = block_count + 1 WHERE username = $1", (nominee_username,))
            await query.edit_message_text(text=f"感谢你的评价！你已为 `@{nominee_username}` 添加了 '{tag_info['tag_name']}' 标签。", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"处理按钮点击时出错: {e}", exc_info=True)
