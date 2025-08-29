import logging
import re
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction # <--- 注意：我们现在导入的是 db_transaction

logger = logging.getLogger(__name__)

async def auto_delete_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """在指定延迟后删除消息。"""
    # 这个函数需要从 context 中获取延迟时间
    delay = context.job.data['delay']
    if delay <= 0: return
    await asyncio.sleep(delay)
    try:
        # 使用 context.job.data 中的 chat_id 和 message_id
        await context.bot.delete_message(
            chat_id=context.job.data['chat_id'],
            message_id=context.job.data['message_id']
        )
        logger.info(f"已自动删除消息 {context.job.data['message_id']}")
    except Exception as e:
        logger.warning(f"自动删除消息失败: {e}")

async def handle_nomination(
    update: Update, 
    context: ContextTypes.DEFAULT_TYPE, 
    direct_username: str | None = None, 
    back_path: str | None = None
):
    nominator_id = update.effective_user.id
    
    nominee_username = None
    if direct_username:
        nominee_username = direct_username
    else:
        if update.message:
            match = re.search(r'@(\S+)', update.message.text)
            if match: nominee_username = match.group(1)

    if not nominee_username:
        if update.callback_query: await update.callback_query.answer()
        elif update.message: await update.message.reply_text("请使用 '查询 @任意符号' 的格式。")
        return

    try:
        # 使用事务进行读取，保证数据一致性
        async with db_transaction() as conn:
            await conn.execute("INSERT INTO users (id) VALUES ($1) ON CONFLICT DO NOTHING", nominator_id)
            await conn.execute("INSERT INTO reputation_profiles (username) VALUES ($1) ON CONFLICT DO NOTHING", nominee_username)
            profile_data = await conn.fetchrow("SELECT * FROM reputation_profiles WHERE username = $1", nominee_username)
            top_tags = await conn.fetch("SELECT t.tag_name, COUNT(v.id) as vote_count FROM tags t JOIN votes v ON t.id = v.tag_id WHERE v.nominee_username = $1 GROUP BY t.tag_name ORDER BY vote_count DESC LIMIT 5;", nominee_username)

        tags_str = ", ".join([f"{t['tag_name']} ({t['vote_count']})" for t in top_tags]) if top_tags else "暂无"
        
        reply_text = (f"符号: `@{nominee_username}`\n\n"
                      f"👍 *推荐*: {profile_data.get('recommend_count', 0)} 次\n"
                      f"👎 *拉黑*: {profile_data.get('block_count', 0)} 次\n\n"
                      f"*收到最多的评价*:\n{tags_str}")

        keyboard = [
            [InlineKeyboardButton("👍 推荐", callback_data=f"vote_up_{nominator_id}_{nominee_username}"),
             InlineKeyboardButton("👎 拉黑", callback_data=f"vote_down_{nominator_id}_{nominee_username}")],
            [InlineKeyboardButton("⭐ 添加到我的收藏", callback_data=f"fav_add_{nominator_id}_{nominee_username}")]
        ]

        if back_path:
            if back_path == 'favs':
                keyboard.append([InlineKeyboardButton("⬅️ 返回收藏夹", callback_data="back_to_favs")])
            elif back_path.startswith('leaderboard'):
                 keyboard.append([InlineKeyboardButton("⬅️ 返回排行榜", callback_data=f"back_to_{back_path}")])
        else:
             keyboard.append([InlineKeyboardButton("⬅️ 返回主菜单", callback_data="back_to_help")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(reply_text, reply_markup=reply_markup, parse_mode='Markdown')
        elif update.message:
            await update.message.reply_text(reply_text, reply_markup=reply_markup, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"处理符号查询时出错: {e}", exc_info=True)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理档案卡上的“推荐”、“拉黑”和“选择标签”按钮。"""
    query = update.callback_query
    data = query.data.split('_')
    action = data[0]
    
    try:
        if action == "vote":
            original_back_path = None
            if query.message and query.message.reply_markup:
                for row in query.message.reply_markup.inline_keyboard:
                    for button in row:
                        if button.callback_data and button.callback_data.startswith('back_to_'):
                            original_back_path = button.callback_data
                            break
                    if original_back_path: break
            
            vote_type, nominator_id_str, nominee_username = data[1], data[2], "_".join(data[3:])
            tag_type = 'recommend' if vote_type == 'up' else 'block'
            
            async with db_transaction() as conn: # 使用事务读取
                tags = await conn.fetch("SELECT id, tag_name FROM tags WHERE type = $1", tag_type)
            
            if not tags:
                await query.edit_message_text(text=f"系统中还没有可用的 '{'推荐' if tag_type == 'recommend' else '拉黑'}' 标签。请先让管理员添加。")
                return

            keyboard = []
            for tag in tags:
                callback_data = f"tag_{tag['id']}_{nominator_id_str}_{nominee_username}"
                if original_back_path:
                    back_path_suffix = original_back_path.replace('back_to_', '_back_')
                    callback_data += f"{back_path_suffix}"
                keyboard.append([InlineKeyboardButton(tag['tag_name'], callback_data=callback_data)])
            
            if original_back_path:
                keyboard.append([InlineKeyboardButton("⬅️ 返回档案卡", callback_data=original_back_path.replace('_back_', '_to_'))])

            await query.edit_message_text(text=f"请为 `@{nominee_username}` 选择一个标签:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

        elif action == "tag":
            # --- 核心灵魂修复：使用 db_transaction 确保原子性 ---
            async with db_transaction() as conn:
                back_index = -1
                try: back_index = data.index('back')
                except ValueError: pass
                
                tag_id, nominator_id = int(data[1]), int(data[2])
                nominee_username = "_".join(data[3:back_index]) if back_index != -1 else "_".join(data[3:])
                back_path_suffix = "_".join(data[back_index+1:]) if back_index != -1 else None

                existing_vote = await conn.fetchrow("SELECT id FROM votes WHERE nominator_id = $1 AND nominee_username = $2 AND tag_id = $3", nominator_id, nominee_username, tag_id)
                if existing_vote:
                    await context.bot.send_message(chat_id=query.from_user.id, text=f"你已经对 `@{nominee_username}` 使用过这个标签了。", parse_mode='Markdown')
                else:
                    await conn.execute("INSERT INTO votes (nominator_id, nominee_username, tag_id) VALUES ($1, $2, $3)", nominator_id, nominee_username, tag_id)
                    tag_info = await conn.fetchrow("SELECT type FROM tags WHERE id = $1", tag_id)
                    column_to_update = "recommend_count" if tag_info['type'] == 'recommend' else "block_count"
                    await conn.execute(f"UPDATE reputation_profiles SET {column_to_update} = {column_to_update} + 1 WHERE username = $1", nominee_username)
            
            # --- 法则执行：刷新档案卡并设置自动关闭 ---
            await handle_nomination(update, context, direct_username=nominee_username, back_path=back_path_suffix)
            
            async with db_transaction() as conn:
                delay_row = await conn.fetchrow("SELECT value FROM settings WHERE key = 'auto_close_delay'")
            
            if delay_row and int(delay_row['value']) > 0:
                context.job_queue.run_once(
                    auto_delete_message,
                    int(delay_row['value']),
                    data={'chat_id': query.message.chat_id, 'message_id': query.message.message_id, 'delay': int(delay_row['value'])},
                    name=f"delete-{query.message.chat_id}-{query.message.message_id}"
                )

    except Exception as e:
        logger.error(f"处理按钮点击时出错: {e}", exc_info=True)
