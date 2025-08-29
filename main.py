import logging
from os import environ
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

from database import db_cursor, init_pool, create_tables
from handlers.reputation import handle_mention_nomination, button_handler as reputation_button_handler, register_user_if_not_exists
from handlers.leaderboard import get_top_board, get_bottom_board, leaderboard_button_handler
from handlers.profile import my_favorites, my_profile
from handlers.admin import set_admin, list_tags, add_tag, remove_tag

load_dotenv()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def grant_creator_admin_privileges():
    """在启动时，为 CREATOR_ID 授予管理员权限。"""
    creator_id_str = environ.get("CREATOR_ID")
    if not creator_id_str:
        logger.warning("未设置 CREATOR_ID 环境变量，无法自动授予创世管理员权限。")
        return
    
    try:
        creator_id = int(creator_id_str)
        with db_cursor() as cur:
            # 检查创世神是否存在
            cur.execute("SELECT is_admin FROM users WHERE id = %s", (creator_id,))
            user = cur.fetchone()
            if not user:
                logger.warning(f"CREATOR_ID {creator_id} 尚未与机器人互动，暂时无法授权。请先私聊机器人。")
                return
            
            # 如果创世神还不是管理员，则授权
            if not user['is_admin']:
                cur.execute("UPDATE users SET is_admin = TRUE WHERE id = %s", (creator_id,))
                logger.info(f"✅ 创世神 {creator_id} 已被自动授予管理员权限。")
            else:
                logger.info(f"创世神 {creator_id} 已经是管理员。")

    except (ValueError, TypeError):
        logger.error(f"CREATOR_ID '{creator_id_str}' 不是一个有效的数字ID。")
    except Exception as e:
        logger.error(f"授予创世神权限时发生错误: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await register_user_if_not_exists(user)
    await update.message.reply_text(
        f"你好，{user.first_name}！欢迎使用社群信誉机器人。\n"
        "在群里发送 `评价 @username` 即可开始。\n"
        "使用 /help 查看所有命令。",
        parse_mode='MarkdownV2'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await register_user_if_not_exists(update.effective_user)
    
    with db_cursor() as cur:
        cur.execute("SELECT is_admin FROM users WHERE id = %s", (user_id,))
        user_data = cur.fetchone()
    
    is_admin = user_data and user_data['is_admin']

    user_help = """
*用户命令:*
`评价 @username` \- 在群里发送以提名用户进行评价\.
/top 或 /红榜 \- 查看推荐排行榜\.
/bottom 或 /黑榜 \- 查看拉黑排行榜\.
/myfavorites \- 查看你的个人收藏夹（私聊发送）\.
/myprofile \- 查看你自己的声望和收到的标签\.
/help \- 显示此帮助信息\.
    """

    admin_help = """
*管理员命令:*
/setadmin `<user_id>` \- 设置一个用户为管理员\.
/listtags \- 列出所有可用的评价标签\.
/addtag `<推荐|拉黑> <标签>` \- 添加一个新的评价标签\.
/removetag `<标签>` \- 移除一个评价标签\.
    """
    
    full_help_text = user_help
    if is_admin:
        full_help_text += "\n" + admin_help

    await update.message.reply_text(full_help_text, parse_mode='MarkdownV2')

async def all_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action = query.data.split('_')[0]

    if action == "fav":
        from handlers.profile import handle_favorite_button
        await handle_favorite_button(query, context)
    elif action in ["vote", "tag"]:
        await reputation_button_handler(update, context)
    elif action == "leaderboard":
        await leaderboard_button_handler(update, context)
    else:
        await query.answer("未知操作")

async def post_init(application: Application):
    """在机器人应用初始化后执行的任务。"""
    await grant_creator_admin_privileges()

def main() -> None:
    logger.info("机器人正在启动...")

    try:
        init_pool()
        create_tables()
    except Exception as e:
        logger.critical(f"数据库初始化失败，机器人无法启动: {e}")
        return

    application = Application.builder().token(environ["TELEGRAM_BOT_TOKEN"]).post_init(post_init).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    
    nomination_filter = (
        filters.TEXT & (filters.Regex('^评价') | filters.Regex('^nominate')) & filters.Entity('mention')
    )
    application.add_handler(MessageHandler(nomination_filter, handle_mention_nomination))

    application.add_handler(CommandHandler("top", get_top_board))
    application.add_handler(CommandHandler("bottom", get_bottom_board))
    application.add_handler(MessageHandler(filters.Regex('^/红榜$'), get_top_board))
    application.add_handler(MessageHandler(filters.Regex('^/黑榜$'), get_bottom_board))

    application.add_handler(CommandHandler("myfavorites", my_favorites))
    application.add_handler(CommandHandler("myprofile", my_profile))
    
    application.add_handler(CommandHandler("setadmin", set_admin))
    application.add_handler(CommandHandler("listtags", list_tags))
    application.add_handler(CommandHandler("addtag", add_tag))
    application.add_handler(CommandHandler("removetag", remove_tag))

    application.add_handler(CallbackQueryHandler(all_button_handler))
    
    logger.info("所有处理器已注册。正在开始轮询...")
    application.run_polling()
    logger.info("机器人已停止。")

if __name__ == '__main__':
    main()
