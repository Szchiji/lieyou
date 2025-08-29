import logging
from os import environ
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

from database import db_cursor, init_pool, create_tables
from handlers.reputation import handle_nomination, button_handler as reputation_button_handler, register_user_if_not_exists
from handlers.leaderboard import get_top_board, get_bottom_board, leaderboard_button_handler
from handlers.profile import my_favorites, my_profile
from handlers.admin import set_admin, list_tags, add_tag, remove_tag

load_dotenv()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Webhook 模式所需的环境变量 ---
TOKEN = environ.get("TELEGRAM_BOT_TOKEN")
# Render 会自动提供 PORT 和 RENDER_EXTERNAL_URL
PORT = int(environ.get('PORT', '8443'))
WEBHOOK_URL = f"{environ.get('RENDER_EXTERNAL_URL')}/{TOKEN}"


async def grant_creator_admin_privileges():
    creator_id_str = environ.get("CREATOR_ID")
    if not creator_id_str: return
    try:
        creator_id = int(creator_id_str)
        with db_cursor() as cur:
            cur.execute("SELECT is_admin FROM users WHERE id = %s", (creator_id,))
            user = cur.fetchone()
            if user and not user['is_admin']:
                cur.execute("UPDATE users SET is_admin = TRUE WHERE id = %s", (creator_id,))
                logger.info(f"✅ 创世神 {creator_id} 已被自动授予管理员权限。")
    except Exception as e:
        logger.error(f"授予创世神权限时发生错误: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await register_user_if_not_exists(user)
    await update.message.reply_text(
        f"你好，{user.first_name}！欢迎使用社群信誉机器人。\n"
        "发送 `查询 @username` 即可查询用户信誉。\n"
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
`查询 @username` \- 查询用户信誉并发起评价\.
`/top` 或 `/红榜` \- 查看推荐排行榜\.
`/bottom` 或 `/黑榜` \- 查看拉黑排行榜\.
`/myfavorites` \- 查看你的个人收藏夹（私聊发送）\.
`/myprofile` \- 查看你自己的声望和收到的标签\.
`/help` \- 显示此帮助信息\.
    """
    admin_help = """
*管理员命令:*
`/setadmin <user_id>` \- 设置一个用户为管理员\.
`/listtags` \- 列出所有可用的评价标签\.
`/addtag <推荐|拉黑> <标签>` \- 添加一个新的评价标签\.
`/removetag <标签>` \- 移除一个评价标签\.
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
    else: await query.answer("未知操作")

async def post_init(application: Application):
    """在应用启动后设置 Webhook 并授予创世神权限。"""
    await application.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES)
    await grant_creator_admin_privileges()

def main() -> None:
    logger.info("机器人正在启动 (Webhook 模式)...")
    try:
        init_pool()
        create_tables()
    except Exception as e:
        logger.critical(f"数据库初始化失败，机器人无法启动: {e}")
        return

    # --- 核心改动：使用 Webhook 模式配置 Application ---
    application = Application.builder().token(TOKEN).post_init(post_init).build()
    
    # 处理器注册保持不变
    nomination_filter = (filters.Regex('^查询') | filters.Regex('^query')) & filters.Entity('mention')
    application.add_handler(MessageHandler(nomination_filter, handle_nomination))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
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
    
    logger.info("所有处理器已注册。正在启动 Webhook 服务器...")

    # --- 核心改动：启动 Webhook 服务器而不是轮询 ---
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL
    )
    
    logger.info("机器人已停止。")

if __name__ == '__main__':
    main()
