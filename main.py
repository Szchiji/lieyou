import asyncio
import logging
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters

import database
from bot_handlers.start import start
from bot_handlers.common import cancel_action
from bot_handlers.menu import show_private_main_menu, private_menu_callback_handler
from bot_handlers.reputation import handle_query, reputation_callback_handler, tag_callback_handler
from bot_handlers.leaderboard import show_leaderboard_callback_handler, leaderboard_type_callback_handler
from bot_handlers.report import generate_my_report
from bot_handlers.admin import (
    admin_panel, manage_tags_panel, manage_menu_buttons_panel, 
    user_management_panel, delete_tag_callback, toggle_tag_callback,
    add_tag_prompt, handle_new_tag, handle_tag_type_selection,
    prompt_for_username, set_user_hidden_status,
    TYPING_TAG_NAME, SELECTING_TAG_TYPE, 
    TYPING_USERNAME_TO_HIDE, TYPING_USERNAME_TO_UNHIDE
)
from bot_handlers.broadcast import (
    prompt_for_broadcast, get_broadcast_content, confirm_broadcast,
    TYPING_BROADCAST, CONFIRM_BROADCAST
)
from bot_handlers.monitoring import run_suspicion_monitor

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def post_init(application: Application) -> None:
    """Initialize bot after startup."""
    await database.init_db()
    
    # Start background monitoring task
    asyncio.create_task(run_suspicion_monitor(application.bot))
    
    logger.info("Bot initialization completed!")

def main() -> None:
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(os.getenv("BOT_TOKEN")).post_init(post_init).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("myreport", generate_my_report))
    application.add_handler(CommandHandler("cancel", cancel_action))

    # Message handlers
    # Handle @mentions in groups
    application.add_handler(MessageHandler(
        filters.MENTION & filters.ChatType.GROUPS, 
        handle_query
    ))
    
    # Handle menu button presses in private chats
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        private_menu_callback_handler
    ))

    # Callback query handlers
    # Admin panel
    application.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(manage_tags_panel, pattern="^admin_manage_tags$"))
    application.add_handler(CallbackQueryHandler(manage_menu_buttons_panel, pattern="^admin_menu_buttons$"))
    application.add_handler(CallbackQueryHandler(user_management_panel, pattern="^admin_user_management$"))
    
    # Tag management
    application.add_handler(CallbackQueryHandler(delete_tag_callback, pattern="^admin_delete_tag_"))
    application.add_handler(CallbackQueryHandler(toggle_tag_callback, pattern="^admin_toggle_tag_"))
    
    # Main menu
    application.add_handler(CallbackQueryHandler(show_private_main_menu, pattern="^show_private_main_menu$"))
    
    # Leaderboard
    application.add_handler(CallbackQueryHandler(show_leaderboard_callback_handler, pattern="^show_leaderboard_public$"))
    application.add_handler(CallbackQueryHandler(leaderboard_type_callback_handler, pattern="^lb_"))
    
    # Reputation
    application.add_handler(CallbackQueryHandler(reputation_callback_handler, pattern="^rep_"))
    application.add_handler(CallbackQueryHandler(tag_callback_handler, pattern="^tag_"))

    # Conversation handlers
    # Tag creation
    tag_creation_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_tag_prompt, pattern="^admin_add_tag_prompt$")],
        states={
            TYPING_TAG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_tag)],
            SELECTING_TAG_TYPE: [CallbackQueryHandler(handle_tag_type_selection, pattern="^tag_type_")]
        },
        fallbacks=[CommandHandler("cancel", cancel_action)]
    )
    application.add_handler(tag_creation_conv)

    # User hiding/unhiding
    user_hide_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(prompt_for_username, pattern="^admin_hide_user_prompt$"),
            CallbackQueryHandler(prompt_for_username, pattern="^admin_unhide_user_prompt$")
        ],
        states={
            TYPING_USERNAME_TO_HIDE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_user_hidden_status)],
            TYPING_USERNAME_TO_UNHIDE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_user_hidden_status)]
        },
        fallbacks=[CommandHandler("cancel", cancel_action)]
    )
    application.add_handler(user_hide_conv)

    # Broadcast
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(prompt_for_broadcast, pattern="^admin_broadcast$")],
        states={
            TYPING_BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND, get_broadcast_content)],
            CONFIRM_BROADCAST: [CallbackQueryHandler(confirm_broadcast, pattern="^broadcast_")]
        },
        fallbacks=[CommandHandler("cancel", cancel_action)]
    )
    application.add_handler(broadcast_conv)

    # Run the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
