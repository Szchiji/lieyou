from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import is_admin

async def send_help_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    发送主帮助/入口菜单。
    - 在私聊中，显示完整的功能菜单。
    - 在群组中，引导用户到私聊。
    """
    # 如果是在群组或超级群组中调用
    if update.message and update.message.chat.type in ['group', 'supergroup']:
        bot_username = context.bot.username
        private_chat_button = InlineKeyboardMarkup([
            [InlineKeyboardButton("👉 前往私聊以使用全部功能", url=f"https://t.me/{bot_username}?start=menu")]
        ])
        await update.message.reply_text(
            "为了避免打扰群内成员，请在私聊窗口与我互动。",
            reply_markup=private_chat_button
        )
        return

    # --- 以下逻辑只会在私聊中执行 ---
    user_id = update.effective_user.id
    
    text = "你好！这是一个声誉评价机器人。\n\n"
    text += "在群聊中 @某人 可以查询或评价其声誉。\n"
    text += "通过下方的按钮，可以访问更多功能。"

    keyboard = [
        [
            InlineKeyboardButton("🏆 排行榜", callback_data="leaderboard_menu"),
            InlineKeyboardButton("❤️ 我的收藏", callback_data="my_favorites_1")
        ]
    ]
    
    if await is_admin(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ 管理员面板", callback_data="admin_panel")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)

    # 在私聊中，无论是命令还是回调，都显示完整的内联菜单
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)
