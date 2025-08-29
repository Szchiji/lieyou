import logging
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
from constants import CALLBACK_LIST_PREFIX

# 日志配置
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

async def main() -> None:
    """启动并运行机器人。"""
    load_dotenv()
    
    # 初始化数据库连接池并创建表
    init_pool()
    create_tables()

    # 创建 Application 实例
    token = environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN 环境变量未设置！")
    
    application = Application.builder().token(token).build()
    
    # 注册命令处理器
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("hunt", hunt))
    application.add_handler(CommandHandler("trap", trap))
    application.add_handler(CommandHandler("list", list_prey))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("leaderboard", leaderboard))

    # 注册回调处理器
    application.add_handler(CallbackQueryHandler(list_prey, pattern=f"^{CALLBACK_LIST_PREFIX}"))

    # 启动机器人
    logging.info("Bot is starting up...")
    await application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
