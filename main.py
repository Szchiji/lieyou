import logging
import asyncio
import os
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
)
# We will use your database file now
import database
# Import from our new, compatible handlers
from bot_handlers.start import start, show_private_main_menu
from bot_handlers.reputation import handle_query, evaluation_callback_handler
# We can add other handlers as we build them, for now keep it simple
# from bot_handlers.admin import ... 

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Main Application Setup ---
async def main():
    """Start the bot."""
    # This will now correctly use your get_pool logic inside database.py
    await database.init_db()

    bot_token = os.environ.get("BOT_TOKEN")
    if not bot_token:
        logger.error("FATAL: BOT_TOKEN environment variable not set.")
        return

    application = Application.builder().token(bot_token).build()

    # --- Handler Registration ---
    # The order is important!
    
    # 1. Commands
    application.add_handler(CommandHandler('start', start))

    # 2. Specific Message Handlers (e.g., for @mentions)
    application.add_handler(MessageHandler(filters.Entity('mention') & filters.ChatType.GROUPS, handle_query))

    # 3. CallbackQuery Handlers (for all button presses)
    application.add_handler(CallbackQueryHandler(show_private_main_menu, pattern=r'^show_private_main_menu$'))
    application.add_handler(CallbackQueryHandler(evaluation_callback_handler, pattern=r'^eval_'))
    # Add a placeholder for other menu buttons
    # application.add_handler(CallbackQueryHandler(private_menu_callback_handler, pattern=r'^menu_'))

    # --- Run the Bot ---
    logger.info("Bot is starting...")
    try:
        async with application:
            # We don't have a monitor function anymore, so we remove it
            # application.create_task(run_suspicion_monitor())
            
            await application.initialize()
            await application.start()
            await application.updater.start_polling()
            logger.info("Bot has started polling successfully.")
            await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot shutdown requested.")
    finally:
        logger.info("Bot shutdown sequence initiated.")
        await database.close_pool() # Correctly close your pool
        if application and application.updater and application.updater.is_polling():
            await application.updater.stop()
        if application:
            await application.shutdown()
        logger.info("Bot has been shut down.")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"Failed to run the bot at the top level: {e}", exc_info=True)
