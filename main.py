import logging
from os import environ
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from database import init_pool, create_tables
from handlers.base import start, help_command
from handlers.prey import trap, list_prey, hunt
from handlers.reputation import leaderboard

# 加载环境变量
load_dotenv()

# 设置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 权限控制 ---
ALLOWED_GROUP_IDS = [int(gid) for gid in environ.get("ALLOWED_GROUP_IDS", "").split(',') if gid]

async def check_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """中间件，检查消息是否来自允许的群组"""
    if not ALLOWED_GROUP_IDS:
        return True # 如果没有设置群组ID，则允许所有
    
    chat_id = update.effective_chat.id
    if chat_id in ALLOWED_GROUP_IDS:
        return True
    
    logger.warning(f"来自不允许的群组 {chat_id} 的访问被拒绝。")
    # 可以选择不回复，或者发送一条提示消息
    # await update.message.reply_text("抱歉，我不能在这个群组工作。")
    return False


async def authorized_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """在执行实际命令前进行权限检查"""
    if await check_group(update, context):
        # 注意：这里需要一种方式来调用原始的命令处理函数
        # telegram-python-bot v21 的处理方式更复杂，我们简化一下
        # 暂时将所有命令处理函数都包装起来
        pass # 实际逻辑在 application.add_handler 中处理


def main() -> None:
    """启动机器人。"""
    logger.info("机器人正在启动...")

    try:
        init_pool()
        create_tables()
    except Exception as e:
        logger.critical(f"数据库初始化失败，机器人无法启动: {e}")
        return

    application = Application.builder().token(environ["TELEGRAM_BOT_TOKEN"]).build()

    # 创建一个过滤器，只处理来自授权群组的命令
    # 如果 ALLOWED_GROUP_IDS 为空, filters.ALL 将匹配所有
    group_filter = filters.Chat(chat_id=ALLOWED_GROUP_IDS) if ALLOWED_GROUP_IDS else filters.ALL

    # 注册命令处理器，并应用群组过滤器
    application.add_handler(CommandHandler("start", start, filters=group_filter))
    application.add_handler(CommandHandler("help", help_command, filters=group_filter))
    application.add_handler(CommandHandler("trap", trap, filters=group_filter))
    application.add_handler(CommandHandler("list", list_prey, filters=group_filter))
    application.add_handler(CommandHandler("hunt", hunt, filters=group_filter))
    application.add_handler(CommandHandler("leaderboard", leaderboard, filters=group_filter))

    logger.info("所有命令处理器已注册。")
    
    application.run_polling()

if __name__ == '__main__':
    main()
