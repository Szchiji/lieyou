import logging
import asyncio
import httpx
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

# --- 环境变量 ---
TOKEN = environ.get("TELEGRAM_BOT_TOKEN")
PORT = int(environ.get('PORT', '8443'))
RENDER_URL = environ.get('RENDER_EXTERNAL_URL')
WEBHOOK_URL = f"{RENDER_URL}/{TOKEN}" if RENDER_URL else None

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
    is_admin = False
    with db_cursor() as cur:
        cur.execute("SELECT is_admin FROM users WHERE id = %s", (user_id,))
        user_data = cur.fetchone()
        if user_data:
            is_admin = user_data['is_admin']
    
    user_help = "...\n*用户命令:*\n`查询 @username` \\- 查询用户信誉并发起评价\\.\n`/top` 或 `/红榜` \\- 查看推荐排行榜\\.\n`/bottom` 或 `/黑榜` \\- 查看拉黑排行榜\\.\n`/myfavorites` \\- 查看你的个人收藏夹（私聊发送）\\.\n`/myprofile` \\- 查看你自己的声望和收到的标签\\.\n`/help` \\- 显示此帮助信息\\."
    admin_help = "\n*管理员命令:*\n`/setadmin <user_id>` \\- 设置一个用户为管理员\\.\n`/listtags` \\- 列出所有可用的评价标签\\.\n`/addtag <推荐|拉黑> <标签>` \\- 添加一个新的评价标签\\.\n`/removetag <标签>` \\- 移除一个评价标签\\."
    
    full_help_text = user_help + (admin_help if is_admin else "")
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
    """
    启动后的终极初始化流程:
    1. 获取并打印当前的 Webhook 信息 (用于诊断).
    2. 强制删除旧的 Webhook, 清除所有陈旧/错误的设置.
    3. 设置全新的、绝对正确的 Webhook.
    """
    try:
        # 1. 获取并打印当前信息
        current_webhook_info = await application.bot.get_webhook_info()
        logger.info(f"🔎 当前 Webhook 信息: {current_webhook_info}")

        # 2. 强制删除旧的 Webhook
        if current_webhook_info.url:
            logger.info("🗑️ 发现旧的 Webhook 地址，正在强制删除...")
            delete_result = await application.bot.delete_webhook()
            logger.info(f"✅ 旧 Webhook 删除成功: {delete_result}")
        else:
            logger.info("ℹ️ 无需删除，当前没有设置 Webhook。")

        # 3. 设置全新的 Webhook
        logger.info(f"🚀 正在设置全新的 Webhook: {WEBHOOK_URL}")
        set_result = await application.bot.set_webhook(
            url=WEBHOOK_URL,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True # 丢弃在机器人离线期间积累的所有旧消息
        )
        logger.info(f"🎉 全新 Webhook 设置成功: {set_result}")

        # 验证最终状态
        final_webhook_info = await application.bot.get_webhook_info()
        logger.info(f"💯 最终确认 Webhook 状态: {final_webhook_info}")
        if final_webhook_info.url != WEBHOOK_URL:
             logger.critical("‼️ 严重警告: 最终 Webhook 地址与目标不符，请检查！")

        await grant_creator_admin_privileges()

    except Exception as e:
        logger.critical(f"❌ 在 post_init 阶段发生致命错误: {e}")


def main() -> None:
    logger.info("机器人正在启动 (Webhook 模式)...")
    if not TOKEN or not WEBHOOK_URL:
        logger.critical("错误: TELEGRAM_BOT_TOKEN 或 RENDER_EXTERNAL_URL 环境变量未设置。")
        return

    try:
        init_pool()
        create_tables()
    except Exception as e:
        logger.critical(f"❌ 数据库初始化失败: {e}")
        return

    application = Application.builder().token(TOKEN).post_init(post_init).build()
    
    # 处理器注册
    application.add_handler(MessageHandler((filters.Regex('^查询') | filters.Regex('^query')) & filters.Entity('mention'), handle_nomination))
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
    application.run_webhook(listen="0.0.0.0", port=PORT, webhook_url=WEBHOOK_URL)
    logger.info("机器人已停止。")

if __name__ == '__main__':
    main()
