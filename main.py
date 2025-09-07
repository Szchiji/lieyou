import logging
import os
import asyncio
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
)

import database
# This will import all necessary handlers from the bot_handlers package
from bot_handlers import *

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """The main entry point for the bot."""
    load_dotenv()
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN not found in environment variables. Bot cannot start.")
        return

    try:
        await database.init_db()
    except Exception as e:
        logger.critical(f"Database initialization failed: {e}. Bot cannot start.", exc_info=True)
        return

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # --- Conversation Handlers ---
    
    # Combined admin conversation handler to manage all admin sub-flows
    admin_conv = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_panel)],
        states={
            0: [ # Base level of the admin panel
                CallbackQueryHandler(admin_panel, pattern=r'^admin_panel$'),
                # Tag Management
                CallbackQueryHandler(manage_tags_panel, pattern=r'^admin_manage_tags$'),
                CallbackQueryHandler(delete_tag_callback, pattern=r'^admin_delete_tag_'),
                # Menu Management (placeholder)
                CallbackQueryHandler(manage_menu_buttons_panel, pattern=r'^admin_menu_buttons$'),
                # User Management
                CallbackQueryHandler(user_management_panel, pattern=r'^admin_user_management$'),
                # Sub-conversations (entry points)
                CallbackQueryHandler(add_tag_prompt, pattern=r'^admin_add_tag_prompt$'),
                CallbackQueryHandler(prompt_for_username, pattern=r'^admin_hide_user_prompt$'),
                CallbackQueryHandler(prompt_for_username, pattern=r'^admin_unhide_user_prompt$'),
                CallbackQueryHandler(prompt_for_broadcast, pattern=r'^admin_broadcast$'),
            ],
            # Sub-conversation states
            TYPING_TAG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_tag)],
            SELECTING_TAG_TYPE: [CallbackQueryHandler(handle_tag_type_selection, pattern=r'^tag_type_')],
            
            TYPING_USERNAME_TO_HIDE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_user_hidden_status)],
            TYPING_USERNAME_TO_UNHIDE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_user_hidden_status)],
            
            TYPING_BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND, get_broadcast_content)],
            CONFIRM_BROADCAST: [CallbackQueryHandler(confirm_broadcast, pattern=r'^broadcast_')],
        },
        fallbacks=[CommandHandler('cancel', cancel_action), CallbackQueryHandler(cancel_action, pattern=r'^cancel$')],
        allow_reentry=True,
    )

    # --- Register Handlers ---
    
    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(admin_conv) # Add the main admin conversation handler
    application.add_handler(CommandHandler("myreport", generate_my_report))
    
    # Messages (Order is important)
    application.add_handler(MessageHandler(filters.Entity("mention") & filters.ChatType.GROUPS, handle_query))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, private_menu_callback_handler))

    # Callback Queries (Specific patterns first)
    application.add_handler(CallbackQueryHandler(tag_callback_handler, pattern=r'^tag_'))
    application.add_handler(CallbackQueryHandler(leaderboard_type_callback_handler, pattern=r'^lb_'))
    application.add_handler(CallbackQueryHandler(reputation_callback_handler, pattern=r'^rep_'))
    
    # Menu entry points
    application.add_handler(CallbackQueryHandler(show_private_main_menu, pattern=r'^show_private_main_menu$'))
    application.add_handler(CallbackQueryHandler(show_leaderboard_callback_handler, pattern=r'^show_leaderboard_public$'))

    # --- Start Background Tasks ---
    monitor_task = asyncio.create_task(run_suspicion_monitor(application.bot))

    # --- Run the Bot ---
    try:
        logger.info("Bot is starting polling...")
        await application.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        logger.info("Bot is shutting down. Cleaning up...")
        monitor_task.cancel()
        await database.close_pool()
        logger.info("Cleanup complete. Goodbye!")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Process interrupted by user.")
    except Exception as e:
        logger.critical(f"Critical error in main execution: {e}", exc_info=True)
