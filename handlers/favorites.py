import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown
from database import db_cursor
# 导入 reputation.py 中的 handle_nomination 函数
from .reputation import handle_nomination

logger = logging.getLogger(__name__)

async def my_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button: bool = False):
    """处理 /myfavorites 命令，以私信方式显示用户的个人收藏夹。"""
    user = update.effective_user
    query = update.callback_query
    try:
        async with db_cursor() as cur:
            favorites = await cur.fetch("SELECT favorite_username FROM favorites WHERE user_id = $1 ORDER BY favorite_username ASC", user.id)
        if not favorites:
            text = "你的收藏夹是空的。"
            reply_markup = None
        else:
            text = "*你的收藏夹*:\n点击符号名称可直接查询，点击垃圾桶可移除。"
            keyboard = []
            for fav in favorites:
                username = fav['favorite_username']
                # 核心改造：将 query_fav 改为 query_direct，以示区分
                keyboard.append([
                    InlineKeyboardButton(f"@{username}", callback_data=f"query_direct_{username}"),
                    InlineKeyboardButton("🗑️ 移除", callback_data=f"fav_remove_{user.id}_{username}")
                ])
            reply_markup = InlineKeyboardMarkup(keyboard)

        if from_button or (query and query.message and query.message.chat.type == 'private'):
             await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='MarkdownV2')
        else:
            await context.bot.send_message(chat_id=user.id, text=text, reply_markup=reply_markup, parse_mode='MarkdownV2')
            if update.message and update.message.chat.type != 'private':
                await update.message.reply_text("你的收藏夹已发送到你的私信中，请注意查收。", quote=True)
    except Exception as e:
        logger.error(f"显示收藏夹时出错: {e}", exc_info=True)
        if query:
            await query.answer("显示收藏夹失败，发生内部错误。", show_alert=True)

async def handle_favorite_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """统一处理所有与收藏夹相关的按钮点击。"""
    query = update.callback_query
    data = query.data.split('_')
    action_type = data[0] # fav, query
    command = data[1] # add, remove, direct

    if action_type == 'fav':
        user_id_str, favorite_username = data[2], "_".join(data[3:])
        user_id = int(user_id_str)
        if query.from_user.id != user_id:
            await query.answer("这是别人的收藏按钮哦。", show_alert=True)
            return
        try:
            async with db_cursor() as cur:
                if command == "add":
                    await cur.execute("INSERT INTO favorites (user_id, favorite_username) VALUES ($1, $2) ON CONFLICT DO NOTHING", user_id, favorite_username)
                    await query.answer(f"已将 @{favorite_username} 添加到你的收藏夹！", show_alert=False)
                elif command == "remove":
                    await cur.execute("DELETE FROM favorites WHERE user_id = $1 AND favorite_username = $2", user_id, favorite_username)
                    await my_favorites(update, context, from_button=True)
                    await query.answer(f"已从收藏夹中移除 @{favorite_username}。")
        except Exception as e:
            logger.error(f"处理收藏夹按钮时出错: {e}", exc_info=True)
            await query.answer("操作失败，发生内部错误。", show_alert=True)
            
    elif action_type == 'query' and command == 'direct':
        # --- 核心改造：不再伪装，而是直接、坦诚地调用 ---
        favorite_username = "_".join(data[2:])
        # 直接调用 handle_nomination，并将用户名作为参数传递
        await handle_nomination(update, context, direct_username=favorite_username)
