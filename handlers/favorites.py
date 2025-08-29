import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown
from database import db_cursor
# 导入 reputation.py 中的 handle_nomination 函数，以便在点击收藏夹中的条目时能复用查询逻辑
from .reputation import handle_nomination

logger = logging.getLogger(__name__)

async def my_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button: bool = False):
    """
    处理 /myfavorites 命令，以私信方式显示用户的个人收藏夹。
    """
    user = update.effective_user
    query = update.callback_query

    try:
        async with db_cursor() as cur:
            # 从数据库获取该用户收藏的所有“符号”
            favorites = await cur.fetch(
                "SELECT favorite_username FROM favorites WHERE user_id = $1 ORDER BY favorite_username ASC",
                user.id
            )

        if not favorites:
            text = "你的收藏夹是空的。"
            reply_markup = None
        else:
            text = "*你的收藏夹*:\n点击符号名称可直接查询，点击垃圾桶可移除。"
            keyboard = []
            for fav in favorites:
                username = fav['favorite_username']
                # 为每个收藏的符号创建一行按钮：一个是符号本身（点击可查询），另一个是移除按钮
                keyboard.append([
                    InlineKeyboardButton(f"@{username}", callback_data=f"query_fav_{username}"),
                    InlineKeyboardButton("🗑️ 移除", callback_data=f"fav_remove_{user.id}_{username}")
                ])
            reply_markup = InlineKeyboardMarkup(keyboard)

        # 如果是从按钮（例如“移除”后刷新）调用的，就编辑原消息
        if from_button or (query and query.message.chat.type == 'private'):
             await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='MarkdownV2')
        else:
            # 否则，作为命令的响应，发送新的私信
            await context.bot.send_message(chat_id=user.id, text=text, reply_markup=reply_markup, parse_mode='MarkdownV2')
            # 如果命令是在群里发的，给一个提示，告诉用户去查收私信
            if update.message and update.message.chat.type != 'private':
                await update.message.reply_text("你的收藏夹已发送到你的私信中，请注意查收。", quote=True)

    except Exception as e:
        logger.error(f"显示收藏夹时出错: {e}", exc_info=True)
        # 尝试通知用户操作失败
        if query:
            await query.answer("显示收藏夹失败，发生内部错误。", show_alert=True)

async def handle_favorite_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    统一处理所有与收藏夹相关的按钮点击 (添加/移除/从收藏夹查询)。
    """
    query = update.callback_query
    data = query.data.split('_')
    action = data[1] # fav_add -> add, fav_remove -> remove
    
    # 格式: "fav_ACTION_userID_favoriteUsername" 或 "query_fav_favoriteUsername"
    if data[0] == 'fav':
        user_id_str, favorite_username = data[2], "_".join(data[3:])
        user_id = int(user_id_str)

        # 安全检查：确保是本人操作自己的收藏夹
        if query.from_user.id != user_id:
            await query.answer("这是别人的收藏按钮哦。", show_alert=True)
            return

        try:
            async with db_cursor() as cur:
                if action == "add":
                    # 插入或忽略，避免重复
                    await cur.execute(
                        "INSERT INTO favorites (user_id, favorite_username) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                        user_id, favorite_username
                    )
                    await query.answer(f"已将 @{favorite_username} 添加到你的收藏夹！", show_alert=False)
                elif action == "remove":
                    # 从收藏夹中删除
                    await cur.execute(
                        "DELETE FROM favorites WHERE user_id = $1 AND favorite_username = $2",
                        user_id, favorite_username
                    )
                    # 刷新收藏夹列表
                    await my_favorites(update, context, from_button=True)
                    await query.answer(f"已从收藏夹中移除 @{favorite_username}。")

        except Exception as e:
            logger.error(f"处理收藏夹按钮时出错: {e}", exc_info=True)
            await query.answer("操作失败，发生内部错误。", show_alert=True)

    elif data[0] == 'query':
        # 用户在收藏夹列表中点击了某个符号名称
        favorite_username = "_".join(data[2:])
        # 伪造一个消息对象，让 handle_nomination 函数能够处理
        query.message.text = f"查询 @{favorite_username}"
        # 直接调用 handle_nomination，就好像用户自己发送了查询命令一样
        await handle_nomination(query, context)
