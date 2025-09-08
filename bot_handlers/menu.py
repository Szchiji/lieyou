from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes
import database

# --- Predefined actions that can be assigned to buttons ---
# The key is the action_id stored in the DB, the value is the callback_data for the handler
AVAILABLE_ACTIONS = {
    "show_leaderboard": "show_leaderboard_public",
    "show_my_favorites": "show_my_favorites_private",
    "show_help": "show_help_private",
    # Add more actions here as they are created
}

async def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Builds the main menu keyboard from the database."""
    buttons = await database.db_fetch_all(
        "SELECT name, action_id FROM menu_buttons WHERE is_active = TRUE ORDER BY sort_order ASC"
    )
    keyboard = [[KeyboardButton(button['name'])] for button in buttons]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def show_private_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the main menu in a private chat."""
    keyboard = await get_main_menu_keyboard()
    # Check if we are editing a message or sending a new one
    if update.callback_query:
        await update.callback_query.message.reply_text(
            "🚀 **主菜单**\n请选择一个操作：",
            reply_markup=keyboard
        )
    else:
        await update.message.reply_text(
            "🚀 **主菜单**\n请选择一个操作：",
            reply_markup=keyboard
        )

async def private_menu_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles button presses from the ReplyKeyboardMarkup."""
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

    # Manually create a mock CallbackQuery to reuse existing handlers
    # This is a clever way to unify logic
    from telegram import CallbackQuery
    mock_query = CallbackQuery(
        id=str(update.update_id), 
        user=update.effective_user, 
        chat_instance=str(update.effective_chat.id), 
        data=callback_data
    )
    mock_query.message = update.message
    
    # Manually call the target handler
    # We need to import the handlers here to avoid circular imports
    from .leaderboard import show_leaderboard_callback_handler
    # from .favorites import show_my_favorites_handler # Example for favorites
    
    handler_map = {
        "show_leaderboard_public": show_leaderboard_callback_handler,
        # "show_my_favorites_private": show_my_favorites_handler,
    }
    
    target_handler = handler_map.get(callback_data)
    
    if target_handler:
        # Simulate the update object for the handler
        mock_update = Update(update.update_id, mock_query)
        await target_handler(mock_update, context)
    else:
        await update.message.reply_text(f"功能 '{callback_data}' 的处理程序不存在，请联系管理员。")
