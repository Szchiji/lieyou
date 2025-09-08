import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import database

logger = logging.getLogger(__name__)

async def show_private_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the main menu in a private chat."""
    query = update.callback_query
    
    user = update.effective_user
    is_admin = await database.is_user_admin(user.id)
    
    # Fetch dynamic buttons from DB
    menu_buttons = await database.db_fetch_all(
        "SELECT name, action FROM menu_buttons WHERE is_enabled = TRUE ORDER BY display_order ASC"
    )

    keyboard = []
    # Convert DB rows to InlineKeyboardButton objects
    if menu_buttons:
        keyboard.extend([
            InlineKeyboardButton(button['name'], callback_data=button['action'])
            for button in menu_buttons
        ])
        # Arrange buttons in rows of 2
        keyboard = [keyboard[i:i+2] for i in range(0, len(keyboard), 2)]

    if is_admin:
        keyboard.append([InlineKeyboardButton("👑 管理员面板", callback_data='admin_panel')])

    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = f"你好，{user.first_name}！欢迎使用机器人。请选择一个选项："

    if query:
        await query.answer()
        await query.edit_message_text(message_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /start command.
    Greets the user, saves their info to the DB, and shows the main menu.
    """
    user = update.effective_user
    chat = update.effective_chat

    # Only show the main menu in private chats
    if chat.type == 'private':
        try:
            # Save or update user info in the database
            await database.db_execute(
                """
                INSERT INTO users (id, first_name, last_name, username, is_bot, language_code)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (id) DO UPDATE SET
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    username = EXCLUDED.username,
                    last_seen = NOW();
                """,
                user.id, user.first_name, user.last_name, user.username, user.is_bot, user.language_code
            )
            logger.info(f"User {user.full_name} (ID: {user.id}) started the bot or updated their info.")

            # Show the main menu
            await show_private_main_menu(update, context)

        except Exception as e:
            logger.error(f"Error during /start for user {user.id}: {e}", exc_info=True)
            await update.message.reply_text("处理您的请求时发生错误，请稍后再试。")
    else:
        # In group chats, just send a simple acknowledgement
        await update.message.reply_text("机器人已在此群组激活。请通过私聊与我互动以获取完整功能。")
