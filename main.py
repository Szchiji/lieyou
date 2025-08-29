import logging
from os import environ
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

from database import init_pool, create_tables
from handlers.reputation import handle_nomination_via_reply, button_handler as reputation_button_handler, register_user_if_not_exists
from handlers.leaderboard import get_leaderboard_page, leaderboard_button_handler
from handlers.profile import my_favorites, my_profile
from handlers.admin import set_admin, list_tags, add_tag, remove_tag

# 加载环境变量和设置日志
load_dotenv()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /start 命令，注册用户。"""
    user = update.effective_user
    await register_user_if_not_exists(user)
    await update.message.reply_text(
        f"你好，{user.first_name}！欢迎使用社群信誉机器人。\n"
        "通过回复一个人的消息并输入 /nominate 来提名他/她进行评价。\n"
        "使用 /help 查看所有可用命令。"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示帮助信息。"""
    help_text = """
    **用户命令:**
    /nominate - (回复消息使用) 提名一个用户进行评价。
    /top - 查看推荐排行榜（红榜）。
    /bottom - 查看拉黑排行榜（黑榜）。
    /myfavorites - 查看你的个人收藏夹（私聊发送）。
    /myprofile - 查看你自己的声望和收到的标签。
    /help - 显示此帮助信息。

    **管理员命令:**
    /setadmin <user_id> - 设置一个用户为管理员。
    /listtags - 列出所有可用的评价标签。
    /addtag <推荐|拉黑> <标签> - 添加一个新的评价标签。
    /removetag <标签> - 移除一个评价标签。
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')


async def all_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """总按钮分发器。"""
    query = update.callback_query
    action = query.data.split('_')[0]

    if action in ["vote", "tag", "fav"]:
        await reputation_button_handler(update, context)
    elif action == "leaderboard":
        await leaderboard_button_handler(update, context)
    # 其他模块的按钮可以在这里添加
    else:
        await query.answer("未知操作")


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
    
    # 注册命令处理器
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("nominate", handle_nomination_via_reply))
    
    application.add_handler(CommandHandler(["top", "红榜"], get_leaderboard_page))
    application.add_handler(CommandHandler(["bottom", "黑榜"], get_leaderboard_page))
    
    application.add_handler(CommandHandler("myfavorites", my_favorites))
    application.add_handler(CommandHandler("myprofile", my_profile))
    
    # 管理员命令
    application.add_handler(CommandHandler("setadmin", set_admin))
    application.add_handler(CommandHandler("listtags", list_tags))
    application.add_handler(CommandHandler("addtag", add_tag))
    application.add_handler(CommandHandler("removetag", remove_tag))

    # 注册总按钮处理器
    application.add_handler(CallbackQueryHandler(all_button_handler))
    
    logger.info("所有处理器已注册。")
    application.run_polling()

if __name__ == '__main__':
    main()
