import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import database

logger = logging.getLogger(__name__)

async def show_private_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the main menu in a private chat, fetched from the database."""
    query = update.callback_query
    user = update.effective_user

    try:
        # Fetch user's admin status from DB using their TG ID
        db_user = await database.db_fetch_one("SELECT is_admin FROM users WHERE id = $1", user.id)
        is_admin = db_user['is_admin'] if db_user else False

        # Fetch dynamic buttons from DB
        menu_buttons = await database.db_fetch_all(
            "SELECT name, action_id FROM menu_buttons WHERE is_active = TRUE ORDER BY sort_order ASC"
        )

        keyboard_layout = []
        if menu_buttons:
            # Arrange buttons in rows of 2
            row = []
            for button in menu_buttons:
                row.append(InlineKeyboardButton(button['name'], callback_data=button['action_id']))
                if len(row) == 2:
                    keyboard_layout.append(row)
                    row = []
            if row: # Add the last row if it's not full
                keyboard_layout.append(row)

        if is_admin:
            keyboard_layout.append([InlineKeyboardButton("👑 管理员面板", callback_data='admin_panel')])

        reply_markup = InlineKeyboardMarkup(keyboard_layout)
        message_text = f"你好，{user.first_name}！欢迎使用。请选择一个选项："

        if query:
            await query.answer()
            await query.edit_message_text(message_text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(message_text, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error displaying main menu for user {user.id}: {e}", exc_info=True)
        error_msg = "加载主菜单时发生错误，请稍后重试。"
        if query:
            await query.edit_message_text(error_msg)
        else:
            await update.message.reply_text(error_msg)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    user = update.effective_user
    chat = update.effective_chat

    try:
        # This is the correct way to use your database file
        await database.get_or_create_user(user)

        if chat.type == 'private':
            # Now show the main menu
            await show_private_main_menu(update, context)
        else:
            # In group chats, send an acknowledgement
            await update.message.reply_text("机器人已在此群组激活。请通过私聊与我互动以获取完整功能。")

    except Exception as e:
        logger.error(f"Error during /start for user {user.id}: {e}", exc_info=True)
        await update.message.reply_text("处理您的请求时发生错误，请稍后再试。")
