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
    filters
)

import database
from bot_handlers import *
# Import the submodules directly to resolve NameError
from bot_handlers import reputation, leaderboard 

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """The main entry point for the bot."""
    load_dotenv(override=False)
    
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN not found in environment variables. Bot cannot start.")
        return

    # Initialize database
    await database.init_db()

    # Build the application
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # --- Conversation Handlers ---
    add_tag_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_tag_prompt, pattern=r'^admin_add_tag_prompt$')],
        states={
            TYPING_TAG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_tag)],
            SELECTING_TAG_TYPE: [CallbackQueryHandler(handle_new_tag, pattern=r'^tag_type_')],
        },
        fallbacks=[CommandHandler('cancel', cancel_action)],
        conversation_timeout=300
    )

    user_manage_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(prompt_for_username, pattern=r'^admin_hide_user_prompt$'),
            CallbackQueryHandler(prompt_for_username, pattern=r'^admin_unhide_user_prompt$'),
        ],
        states={
            TYPING_USERNAME_TO_HIDE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_user_hidden_status)],
            TYPING_USERNAME_TO_UNHIDE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_user_hidden_status)],
        },
        fallbacks=[CommandHandler('cancel', cancel_action)],
        conversation_timeout=300
    )

    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(prompt_for_broadcast, pattern=r'^admin_broadcast$')],
        states={
            TYPING_BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND, get_broadcast_content)],
            CONFIRM_BROADCAST: [CallbackQueryHandler(confirm_broadcast, pattern=r'^broadcast_')],
        },
        fallbacks=[CommandHandler('cancel', cancel_action)],
        conversation_timeout=600
    )

    # --- Register Handlers ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("myreport", generate_my_report))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, private_menu_callback_handler))
    application.add_handler(MessageHandler(filters.Entity("mention") & filters.ChatType.GROUPS, handle_query))
    application.add_handler(CallbackQueryHandler(reputation_callback_handler, pattern=r'^rep_'))
    application.add_handler(CallbackQueryHandler(reputation.tag_callback_handler, pattern=r'^tag_'))
    application.add_handler(CallbackQueryHandler(show_leaderboard_callback_handler, pattern=r'^show_leaderboard_public$'))
    application.add_handler(CallbackQueryHandler(leaderboard.leaderboard_type_callback_handler, pattern=r'^lb_'))
    application.add_handler(CallbackQueryHandler(admin_panel, pattern=r'^admin_panel$'))
    application.add_handler(CallbackQueryHandler(show_private_main_menu, pattern=r'^show_private_main_menu$'))
    application.add_handler(CallbackQueryHandler(manage_tags_panel, pattern=r'^admin_manage_tags$'))
    application.add_handler(CallbackQueryHandler(delete_tag_callback, pattern=r'^admin_delete_tag_'))
    application.add_handler(CallbackQueryHandler(manage_menu_buttons_panel, pattern=r'^admin_menu_buttons$'))
    application.add_handler(CallbackQueryHandler(user_management_panel, pattern=r'^admin_user_management$'))
    application.add_handler(add_tag_conv)
    application.add_handler(user_manage_conv)
    application.add_handler(broadcast_conv)

    # --- Start Background Tasks (Temporarily Disabled) ---
    # monitor_task = asyncio.create_task(run_suspicion_monitor(application.bot))

    # --- Run the Bot ---
    try:
        logger.info("Bot is starting polling...")
        await application.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        # --- Clean Shutdown ---
        logger.info("Bot is shutting down. Cleaning up...")
        # Since the task was not created, we don't need to cancel it.
        # monitor_task.cancel() 
        await database.close_pool()
        logger.info("Cleanup complete. Goodbye!")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Process interrupted by user.")
    except Exception as e:
        logger.critical(f"Critical error in main execution: {e}", exc_info=True)
