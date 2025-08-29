import logging
import asyncio
from os import environ
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

from database import init_pool, create_tables
from handlers.base import start, help_command
from handlers.hunt_trap import hunt, trap
from handlers.list import list_prey
from handlers.profile import profile
from handlers.leaderboard import leaderboard
from handlers.admin import set_rep
from constants import CALLBACK_LIST_PREFIX

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

async def main() -> None:
    """启动并运行机器人。"""
    load_dotenv()
    
    init_pool()
    create_tables()

    token = environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN 环境变量未设置！")
        return
    
    application = Application.builder().token(token).build()
    
    # 注册命令处理器
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("hunt", hunt))
    application.add_handler(CommandHandler("trap", trap))
    application.add_handler(CommandHandler("list", list_prey))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CommandHandler("setrep", set_rep))

    # 注册回调处理器
    application.add_handler(CallbackQueryHandler(list_prey, pattern=f"^{CALLBACK_LIST_PREFIX}"))

    logger.info("Bot is starting up...")
    await application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    asyncio.run(main())
