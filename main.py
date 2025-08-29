import logging
import asyncio
import uvicorn
from os import environ
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

from database import db_cursor, init_pool, create_tables
from handlers.reputation import handle_nomination, button_handler as reputation_button_handler, register_user_if_not_exists
from handlers.leaderboard import get_top_board, get_bottom_board, leaderboard_button_handler
from handlers.profile import my_favorites, my_profile
from handlers.admin import set_admin, list_tags, add_tag, remove_tag

# --- 日志和环境变量设置 ---
load_dotenv()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = environ.get("TELEGRAM_BOT_TOKEN")
PORT = int(environ.get('PORT', '8443'))
RENDER_URL = environ.get('RENDER_EXTERNAL_URL')
WEBHOOK_URL = f"{RENDER_URL}/{TOKEN}" if RENDER_URL else None
CREATOR_ID = environ.get("CREATOR_ID")

# --- 核心业务逻辑 (Telegram 命令处理) ---
async def grant_creator_admin_privileges(app: Application):
    if not CREATOR_ID: return
    try:
        creator_id = int(CREATOR_ID)
        await register_user_if_not_exists(await app.bot.get_chat(creator_id))
        with db_cursor() as cur:
            cur.execute("UPDATE users SET is_admin = TRUE WHERE id = %s", (creator_id,))
            logger.info(f"✅ 创世神 {creator_id} 已被自动授予管理员权限。")
    except Exception as e:
        logger.error(f"授予创世神权限时发生错误: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await register_user_if_not_exists(user)
    await update.message.reply_text("你好！欢迎使用社群信誉机器人。使用 /help 查看所有命令。")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # (帮助命令内容与之前版本相同)
    user_id = update.effective_user.id
    await register_user_if_not_exists(update.effective_user)
    is_admin = False
    with db_cursor() as cur:
        cur.execute("SELECT is_admin FROM users WHERE id = %s", (user_id,))
        user_data = cur.fetchone()
        if user_data: is_admin = user_data['is_admin']
    
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
    logger.info("正在执行启动后任务...")
    try:
        current_webhook_info = await application.bot.get_webhook_info()
        logger.info(f"🔎 当前 Webhook 信息: {current_webhook_info.url or '无'}")
        if current_webhook_info.url:
            logger.info("🗑️ 正在强制删除旧的 Webhook...")
            if await application.bot.delete_webhook():
                logger.info("✅ 旧 Webhook 删除成功。")
            else:
                logger.warning("⚠️ 删除旧 Webhook 失败，可能已经不存在。")
        
        logger.info(f"🚀 正在设置全新的 Webhook: {WEBHOOK_URL}")
        if await application.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES, drop_pending_updates=True):
            logger.info("🎉 全新 Webhook 设置成功！")
        else:
            logger.critical("❌ 设置 Webhook 失败！")

        await grant_creator_admin_privileges(application)
    except Exception as e:
        logger.critical(f"❌ 在 post_init 阶段发生致命错误: {e}")

async def main() -> None:
    # --- 初始化数据库 ---
    try:
        init_pool()
        create_tables()
        logger.info("✅ 数据库初始化成功。")
    except Exception as e:
        logger.critical(f"❌ 数据库初始化失败，程序终止: {e}")
        return

    # --- 初始化 Telegram Application ---
    ptb_app = Application.builder().token(TOKEN).post_init(post_init).build()
    
    # --- 注册处理器 ---
    ptb_app.add_handler(MessageHandler((filters.Regex('^查询') | filters.Regex('^query')) & filters.Entity('mention'), handle_nomination))
    ptb_app.add_handler(CommandHandler("start", start))
    ptb_app.add_handler(CommandHandler("help", help_command))
    ptb_app.add_handler(CommandHandler("top", get_top_board))
    ptb_app.add_handler(CommandHandler("bottom", get_bottom_board))
    ptb_app.add_handler(MessageHandler(filters.Regex('^/红榜$'), get_top_board))
    ptb_app.add_handler(MessageHandler(filters.Regex('^/黑榜$'), get_bottom_board))
    ptb_app.add_handler(CommandHandler("myfavorites", my_favorites))
    ptb_app.add_handler(CommandHandler("myprofile", my_profile))
    ptb_app.add_handler(CommandHandler("setadmin", set_admin))
    ptb_app.add_handler(CommandHandler("listtags", list_tags))
    ptb_app.add_handler(CommandHandler("addtag", add_tag))
    ptb_app.add_handler(CommandHandler("removetag", remove_tag))
    ptb_app.add_handler(CallbackQueryHandler(all_button_handler))
    logger.info("✅ 所有 Telegram 处理器已注册。")

    # --- 创建一个 FastAPI 应用来包装 PTB ---
    from fastapi import FastAPI, Request, Response
    
    fastapi_app = FastAPI()

    @fastapi_app.on_event("startup")
    async def startup_event():
        logger.info("FastAPI 应用启动，初始化 PTB...")
        await ptb_app.initialize()
        await ptb_app.post_init(ptb_app)
        await ptb_app.start()
        logger.info("✅ PTB 应用已在后台启动。")

    @fastapi_app.on_event("shutdown")
    async def shutdown_event():
        logger.info("FastAPI 应用关闭，正在停止 PTB...")
        await ptb_app.stop()
        await ptb_app.shutdown()
        logger.info("✅ PTB 应用已停止。")

    # 健康检查端点
    @fastapi_app.get("/")
    async def health_check():
        logger.info("❤️ 收到来自 Render 的健康检查请求。")
        return {"status": "OK, I am alive!"}

    # Webhook 端点
    @fastapi_app.post(f"/{TOKEN}")
    async def process_telegram_update(request: Request):
        update_data = await request.json()
        update = Update.de_json(data=update_data, bot=ptb_app.bot)
        await ptb_app.process_update(update)
        return Response(status_code=200)

    # --- 启动服务器 ---
    logger.info("🚀 准备启动 Uvicorn 服务器...")
    config = uvicorn.Config(app=fastapi_app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    if not TOKEN or not WEBHOOK_URL:
        logger.critical("错误: 环境变量 TELEGRAM_BOT_TOKEN 或 RENDER_EXTERNAL_URL 未设置。程序终止。")
    else:
        asyncio.run(main())
