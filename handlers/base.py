from telegram import Update
from telegram.ext import ContextTypes
from database import create_tables, get_db_cursor
import logging

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """当用户发送 /start 时，将用户添加到数据库。"""
    user = update.effective_user
    logger.info(f"用户 {user.id} ({user.username}) 使用了 /start")
    try:
        with get_db_cursor() as cur:
            cur.execute(
                "INSERT INTO users (id, username, first_name) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (user.id, user.username, user.first_name)
            )
        await update.message.reply_text('你好，猎手！欢迎使用猎手机器人。使用 /help 查看所有命令。')
        logger.info(f"成功为用户 {user.id} 初始化或确认数据库记录。")
    except Exception as e:
        logger.error(f"处理 /start 命令时出错，用户ID: {user.id}。错误: {e}")
        await update.message.reply_text('抱歉，初始化时遇到问题，请稍后再试。')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """发送一条包含所有可用命令的消息。"""
    help_text = """
    欢迎使用猎手机器人！
    
    可用命令:
    /start - 开始使用机器人
    /help - 显示此帮助消息
    
    猎物管理:
    /trap <猎物名称> - 捕捉一只猎物
    /list - 查看你捕捉的所有猎物
    /hunt <猎物ID> - 狩猎一只猎物 (将其标记为已处理)
    
    声望系统:
    /leaderboard - 查看猎手声望排行榜
    """
    await update.message.reply_text(help_text)
