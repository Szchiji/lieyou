from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import database

# --- Predefined actions that can be assigned to buttons ---
# The key is the action_id stored in the DB, the value is the callback_data for the handler
AVAILABLE_ACTIONS = {
    "show_leaderboard": "show_leaderboard_public",
    "show_my_favorites": "show_my_favorites_private",
    "show_help": "show_help_private",
    "generate_my_report": "generate_my_report_private" # Example for a new action
}

async def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Builds the main menu keyboard from the database."""
    buttons = await database.db_fetch_all(
        "SELECT name FROM menu_buttons WHERE is_active = TRUE ORDER BY sort_order ASC, name ASC"
    )
    keyboard = [[KeyboardButton(button['name'])] for button in buttons]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

async def show_private_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the main menu in a private chat."""
    keyboard = await get_main_menu_keyboard()
    text = "🚀 **主菜单**\n请使用下方键盘选择一个操作："
    
    # Check if we are coming from a callback query (like "back to menu")
    if update.callback_query:
        await update.callback_query.answer()
        # Edit the previous message to remove inline keyboard
        await update.callback_query.edit_message_text("返回主菜单...")
        # Then send the new menu with ReplyKeyboard
        await update.callback_query.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')

async def private_menu_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles button presses from the ReplyKeyboardMarkup by mapping them to callback handlers."""
    button_text = update.message.text
    
    # Find the action associated with the button text
    action_id = await database.db_fetch_val(
        "SELECT action_id FROM menu_buttons WHERE name = $1 AND is_active = TRUE",
        button_text
    )

    if not action_id:
        await update.message.reply_text("未知命令，请使用键盘上的按钮。")
        return

    # Get the corresponding callback_data for the action
    callback_data = AVAILABLE_ACTIONS.get(action_id)

    if not callback_data:
        await update.message.reply_text(f"功能 '{action_id}' 尚未配置，请联系管理员。")
        return

    # To reuse existing callback handlers, we need to find the handler function.
    # This avoids duplicating logic.
    # We import handlers here to avoid circular dependencies at the top level.
    from .leaderboard import show_leaderboard_callback_handler
    from .report import generate_my_report
    # from .favorites import show_my_favorites_handler # Example for favorites
    
    handler_map = {
        "show_leaderboard_public": show_leaderboard_callback_handler,
        # "show_my_favorites_private": show_my_favorites_handler,
        "generate_my_report_private": generate_my_report
    }
    
    target_handler = handler_map.get(callback_data)
    
    if target_handler:
        # For handlers expecting a CallbackQuery, we create a mock one.
        # For handlers expecting a normal Update (like commands), we can call them directly.
        if callback_data in ["show_leaderboard_public"]:
             from telegram import CallbackQuery
             mock_query = CallbackQuery(id=str(update.update_id), user=update.effective_user, chat_instance=str(update.effective_chat.id), data=callback_data, message=update.message)
             mock_update = Update(update.update_id, mock_query)
             await target_handler(mock_update, context)
        else:
            # This handler (like generate_my_report) is a normal command handler
            await target_handler(update, context)
    else:
        await update.message.reply_text(f"功能 '{callback_data}' 的处理程序不存在，请联系管理员。")
