import logging
import asyncio
import uvicorn
from os import environ
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from telegram import Update, User
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

from database import db_cursor, init_pool, create_tables
from handlers.reputation import handle_nomination, button_handler as reputation_button_handler, register_user_if_not_exists
from handlers.leaderboard import get_top_board, get_bottom_board, leaderboard_button_handler
from handlers.profile import my_favorites, my_profile
from handlers.admin import set_admin, list_tags, add_tag, remove_tag

# --- 日志和环境变量设置 ---
load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = environ.get("TELEGRAM_BOT_TOKEN")
PORT = int(environ.get('PORT', '10000'))
RENDER_URL = environ.get('RENDER_EXTERNAL_URL')
WEBHOOK_URL = f"{RENDER_URL}/{TOKEN}" if RENDER_URL else None
CREATOR_ID = environ.get("CREATOR_ID")

# --- 核心业务逻辑 ---
async def grant_creator_admin_privileges(app: Application):
    if not CREATOR_ID: return
    try:
        creator_id = int(CREATOR_ID)
        chat = await app.bot.get_chat(creator_id)
        creator_user = User(id=chat.id, first_name=chat.first_name, is_bot=False, username=chat.username)
        await register_user_if_not_exists(creator_user)
        async with db_cursor() as cur:
            await cur.execute("UPDATE users SET is_admin = TRUE WHERE id = $1", creator_id)
        logger.info(f"✅ 创世神 {creator_id} 已被自动授予管理员权限。")
    except Exception as e:
        logger.error(f"❌ 授予创世神权限时发生错误: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await register_user_if_not_exists(update.effective_user)
    await update.message.reply_text("你好！欢迎使用社群信誉机器人。使用 /help 查看所有命令。")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await register_user_if_not_exists(update.effective_user)
    is_admin = False
    async with db_cursor() as cur:
        user_data = await cur.fetchrow("SELECT is_admin FROM users WHERE id = $1", update.effective_user.id)
        if user_data: is_admin = user_data['is_admin']
    
    user_help = ("用户命令:\n查询 @username - 查询用户信誉并发起评价。\n/top 或 /红榜 - 查看推荐排行榜。\n"
                 "/bottom 或 /黑榜 - 查看拉黑排行榜。\n/myfavorites - 查看你的个人收藏夹（私聊发送）。\n"
                 "/myprofile - 查看你自己的声望和收到的标签。\n/help - 显示此帮助信息。")
    admin_help = ("\n\n管理员命令:\n/setadmin <user_id> - 设置一个用户为管理员。\n/listtags - 列出所有可用的评价标签。\n"
                  "/addtag <推荐|拉黑> <标签> - 添加一个新的评价标签。\n/removetag <标签> - 移除一个评价标签。")
    await update.message.reply_text(user_help + (admin_help if is_admin else ""))

async def all_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action = query.data.split('_')[0]
    if action == "fav": await handle_favorite_button(query, context)
    elif action in ["vote", "tag"]: await reputation_button_handler(update, context)
    elif action == "leaderboard": await leaderboard_button_handler(update, context)
    else: await query.answer("未知操作")

async def post_init(application: Application):
    logger.info("正在执行启动后任务...")
    try:
        current_webhook_info = await application.bot.get_webhook_info()
        if current_webhook_info.url:
            logger.info("🗑️ 正在强制删除旧的 Webhook...")
            await application.bot.delete_webhook()
        
        logger.info(f"🚀 正在设置全新的 Webhook: {WEBHOOK_URL}")
        await application.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        logger.info("🎉 全新 Webhook 设置成功！")
        await grant_creator_admin_privileges(application)
    except Exception as e:
        logger.critical(f"❌ 在 post_init 阶段发生致命错误: {e}")

@asynccontextmanager
async def lifespan(app: "FastAPI"):
    logger.info("FastAPI 应用启动，初始化 PTB...")
    ptb_app = Application.builder().token(TOKEN).build()
    # 注册处理器
    ptb_app.add_handler(MessageHandler((filters.Regex('^查询') | filters.Regex('^query')) & filters.Entity('mention'), handle_nomination))
    ptb_app.add_handler(CommandHandler(["start", "help"], start)) # 简化
    ptb_app.add_handler(CommandHandler(["top", "红榜"], get_top_board))
    ptb_app.add_handler(CommandHandler(["bottom", "黑榜"], get_bottom_board))
    ptb_app.add_handler(CommandHandler("myfavorites", my_favorites))
    ptb_app.add_handler(CommandHandler("myprofile", my_profile))
    ptb_app.add_handler(CommandHandler("setadmin", set_admin))
    ptb_app.add_handler(CommandHandler("listtags", list_tags))
    ptb_app.add_handler(CommandHandler("addtag", add_tag))
    ptb_app.add_handler(CommandHandler("removetag", remove_tag))
    ptb_app.add_handler(CallbackQueryHandler(all_button_handler))
    
    await ptb_app.initialize()
    await post_init(ptb_app)
    await ptb_app.start()
    app.state.ptb_app = ptb_app
    logger.info("✅ PTB 应用已在后台启动。")
    yield
    logger.info("FastAPI 应用关闭，正在停止 PTB...")
    await app.state.ptb_app.stop()
    await app.state.ptb_app.shutdown()
    logger.info("✅ PTB 应用已停止。")

def main():
    from fastapi import FastAPI, Request, Response
    
    fastapi_app = FastAPI(lifespan=lifespan)

    @fastapi_app.get("/")
    async def health_check(): return {"status": "OK, I am alive!"}

    @fastapi_app.post(f"/{TOKEN}")
    async def process_telegram_update(request: Request):
        try:
            ptb_app = request.app.state.ptb_app
            update_data = await request.json()
            update = Update.de_json(data=update_data, bot=ptb_app.bot)
            await ptb_app.process_update(update)
            return Response(status_code=200)
        except Exception as e:
            logger.error(f"处理更新时发生错误: {e}")
            return Response(status_code=500)

    logger.info("🚀 准备启动 Uvicorn 服务器...")
    uvicorn.run(fastapi_app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    if not all([TOKEN, RENDER_URL]):
        logger.critical("错误: 环境变量 TELEGRAM_BOT_TOKEN 或 RENDER_EXTERNAL_URL 未设置。")
    else:
        # 在启动前，先初始化一次数据库，确保表结构正确
        async def setup():
            await init_pool()
            await create_tables()
        asyncio.run(setup())
        main()
