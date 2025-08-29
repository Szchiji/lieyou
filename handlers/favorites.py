import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction # <--- 注意：我们现在导入的是 db_transaction
from .reputation import handle_nomination

logger = logging.getLogger(__name__)

async def my_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button: bool = False):
    """Displays the user's list of favorites."""
    user = update.effective_user
    query = update.callback_query
    
    try:
        # 使用事务进行读取
        async with db_transaction() as conn:
            favorites = await conn.fetch("SELECT favorite_username FROM favorites WHERE user_id = $1 ORDER BY favorite_username ASC", user.id)
        
        text = "*你的收藏夹*:\n"
        keyboard = []

        if not favorites:
            text += "\n你的收藏夹是空的。"
        else:
            text += "(点击下方按钮直接查询或移除)\n"
            for fav in favorites:
                username = fav['favorite_username']
                query_callback = f"query_direct_{username}_back_favs"
                remove_callback = f"fav_remove_{user.id}_{username}"
                keyboard.append([
                    InlineKeyboardButton(f"@{username}", callback_data=query_callback),
                    InlineKeyboardButton("🗑️ 移除", callback_data=remove_callback)
                ])

        keyboard.append([InlineKeyboardButton("⬅️ 返回主菜单", callback_data="back_to_help")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        # 统一处理消息发送/编辑
        if from_button or query:
             await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            # 尝试私聊发送收藏夹
            try:
                await context.bot.send_message(chat_id=user.id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
                if update.message and update.message.chat.type != 'private':
                    await update.message.reply_text("你的收藏夹已发送到你的私信中，请注意查收。", reply_to_message_id=update.message.message_id)
            except Exception as e:
                logger.warning(f"无法向用户 {user.id} 发送私信: {e}")
                if update.message:
                    await update.message.reply_text("我无法给你发送私信。请先与我开始对话，然后再试一次。", reply_to_message_id=update.message.message_id)


    except Exception as e:
        logger.error(f"显示收藏夹时出错: {e}", exc_info=True)


async def handle_favorite_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles button presses related to favorites (add, remove, query)."""
    query = update.callback_query
    parts = query.data.split('_')
    action_type = parts[0]

    try:
        if action_type == 'query':
            back_index = -1
            try: back_index = parts.index('back')
            except ValueError: pass

            username = "_".join(parts[2:back_index]) if back_index != -1 else "_".join(parts[2:])
            back_path = "_".join(parts[back_index+1:]) if back_index != -1 else None
            
            await handle_nomination(update, context, direct_username=username, back_path=back_path)

        elif action_type == 'fav':
            command = parts[1]
            user_id = int(parts[2])
            username = "_".join(parts[3:])

            if query.from_user.id != user_id:
                await query.answer("这是别人的收藏按钮哦。", show_alert=True)
                return

            # 使用事务进行写入
            async with db_transaction() as conn:
                if command == "add":
                    await conn.execute("INSERT INTO favorites (user_id, favorite_username) VALUES ($1, $2) ON CONFLICT DO NOTHING", user_id, username)
                    await query.answer(f"已将 @{username} 添加到你的收藏夹！", show_alert=False)
                elif command == "remove":
                    await conn.execute("DELETE FROM favorites WHERE user_id = $1 AND favorite_username = $2", user_id, username)
                    # 刷新收藏夹列表
                    await my_favorites(update, context, from_button=True)
                    await query.answer(f"已从收藏夹中移除 @{username}。")
    except Exception as e:
        logger.error(f"处理收藏夹按钮时出错: {e}", exc_info=True)
