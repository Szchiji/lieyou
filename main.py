import logging
import uvicorn
from os import environ
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from telegram import Update, User
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from fastapi import FastAPI, Request, Response

# --- 导入所有模块和处理器 ---
from database import init_pool, create_tables, db_cursor
from handlers.reputation import handle_nomination, button_handler as reputation_button_handler, register_user_if_not_exists
from handlers.leaderboard import get_top_board, get_bottom_board, show_leaderboard
from handlers.profile import my_favorites, my_profile, handle_favorite_button
from handlers.admin import set_admin, list_tags, add_tag, remove_tag

# --- 日志和环境变量设置 ---
load_dotenv()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

TOKEN = environ.get("TELEGRAM_BOT_TOKEN")
PORT = int(environ.get('PORT', '10000'))
RENDER_URL = environ.get('RENDER_EXTERNAL_URL')
WEBHOOK_URL = f"{RENDER_URL}/{TOKEN}" if RENDER_URL else None
CREATOR_ID = environ.get("CREATOR_ID")

# --- 核心业务逻辑 (Telegram 命令处理) ---

async def grant_creator_admin_privileges(app: Application):
    """在启动时自动为创世神授予管理员权限。"""
    if not CREATOR_ID:
        logger.warning("未设置 CREATOR_ID，跳过创世神权限授予。")
        return
    try:
        creator_id = int(CREATOR_ID)
        # 注意：get_chat 可能会因为机器人未被用户启动而失败，但对Creator通常可行
        chat = await app.bot.get_chat(creator_id)
        creator_user = User(id=chat.id, first_name=chat.first_name or "Creator", is_bot=False, username=chat.username)
        await register_user_if_not_exists(creator_user)
        async with db_cursor() as cur:
            await cur.execute("UPDATE users SET is_admin = TRUE WHERE id = $1", creator_id)
        logger.info(f"✅ 创世神 {creator_id} (@{creator_user.username}) 已被自动授予管理员权限。")
    except Exception as e:
        logger.error(f"❌ 授予创世神权限时发生错误: {e}", exc_info=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /start 命令。"""
    await register_user_if_not_exists(update.effective_user)
    await update.message.reply_text("你好！我是社群信誉机器人。使用 /help 查看所有命令。")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /help 命令，根据用户是否为管理员显示不同内容。"""
    await register_user_if_not_exists(update.effective_user)
    is_admin_user = False
    try:
        async with db_cursor() as cur:
            user_data = await cur.fetchrow("SELECT is_admin FROM users WHERE id = $1", update.effective_user.id)
            if user_data:
                is_admin_user = user_data['is_admin']
    except Exception as e:
        logger.error(f"查询用户权限时出错: {e}")

    user_help = (
        "**用户命令:**\n"
        "`查询 @username` - 查询用户信誉并发起评价。\n"
        "`/top` 或 `/红榜` - 查看推荐排行榜。\n"
        "`/bottom` 或 `/黑榜` - 查看拉黑排行榜。\n"
        "`/myfavorites` - 查看你的个人收藏夹（私聊发送）。\n"
        "`/myprofile` - 查看你自己的档案。\n"
        "`/help` - 显示此帮助信息。"
    )
    admin_help = (
        "\n\n**管理员命令:**\n"
        "`/setadmin <user_id>` - 设置用户为管理员。\n"
        "`/listtags` - 列出所有评价标签。\n"
        "`/addtag <推荐|拉黑> <标签>` - 添加新标签。\n"
        "`/removetag <标签>` - 移除一个标签。"
    )
    full_help_text = user_help + (admin_help if is_admin_user else "")
    await update.message.reply_text(full_help_text, parse_mode='Markdown')

async def all_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """统一的按钮回调调度中心。"""
    query = update.callback_query
    # 立即响应按钮点击，给用户即时反馈
    await query.answer()

    data = query.data.split('_')
    action = data[0]

    try:
        if action == "fav":
            await handle_favorite_button(query, context)
        elif action in ["vote", "tag"]:
            await reputation_button_handler(update, context)
        elif action == "leaderboard":
            if data[1] == "noop":  # "第 x/y 页" 按钮，无需操作
                return
            board_type = data[1]  # 'top' or 'bottom'
            page = int(data[2])   # 要跳转的页码
            await show_leaderboard(update, context, board_type, page)
        else:
            logger.warning(f"收到未知的按钮回调数据: {query.data}")
    except Exception as e:
        logger.error(f"处理按钮回调 {query.data} 时发生错误: {e}", exc_info=True)
        try:
            await query.edit_message_text("处理您的请求时发生错误。")
        except Exception:
            pass # 如果消息无法编辑，则忽略

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 应用的生命周期管理器，负责初始化和关闭。"""
    logger.info("🚀 FastAPI 应用启动，正在初始化...")
    await init_pool()
    await create_tables()
    
    ptb_app = Application.builder().token(TOKEN).build()
    
    # --- 注册所有处理器 ---
    # 查询命令
    ptb_app.add_handler(MessageHandler((filters.Regex('^查询') | filters.Regex('^query')) & filters.Entity('mention'), handle_nomination))
    # 基础命令
    ptb_app.add_handler(CommandHandler("start", start))
    ptb_app.add_handler(CommandHandler("help", help_command))
    # 排行榜命令
    ptb_app.add_handler(CommandHandler("top", get_top_board))
    ptb_app.add_handler(MessageHandler(filters.Regex('^/红榜$'), get_top_board))
    ptb_app.add_handler(CommandHandler("bottom", get_bottom_board))
    ptb_app.add_handler(MessageHandler(filters.Regex('^/黑榜$'), get_bottom_board))
    # 个人资料命令
    ptb_app.add_handler(CommandHandler("myfavorites", my_favorites))
    ptb_app.add_handler(CommandHandler("myprofile", my_profile))
    # 管理员命令
    ptb_app.add_handler(CommandHandler("setadmin", set_admin))
    ptb_app.add_handler(CommandHandler("listtags", list_tags))
    ptb_app.add_handler(CommandHandler("addtag", add_tag))
    ptb_app.add_handler(CommandHandler("removetag", remove_tag))
    # 统一按钮回调处理器
    ptb_app.add_handler(CallbackQueryHandler(all_button_handler))
    
    await ptb_app.initialize()
    logger.info(f"正在设置 Webhook: {WEBHOOK_URL}")
    await ptb_app.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    await grant_creator_admin_privileges(ptb_app)
    await ptb_app.start()
    app.state.ptb_app = ptb_app
    logger.info("✅ PTB 应用已在后台启动，准备接收请求。")
    yield
    logger.info("🔌 FastAPI 应用关闭，正在停止 PTB...")
    await app.state.ptb_app.stop()
    await app.state.ptb_app.shutdown()
    logger.info("✅ PTB 应用已优雅地停止。")

def main():
    """主程序入口：配置并启动 FastAPI 和 Uvicorn。"""
    fastapi_app = FastAPI(lifespan=lifespan)

    @fastapi_app.get("/", include_in_schema=False)
    async def health_check():
        """Render 健康检查端点。"""
        return {"status": "OK, I am alive and well!"}

    @fastapi_app.post(f"/{TOKEN}", include_in_schema=False)
    async def process_telegram_update(request: Request):
        """接收 Telegram Webhook 请求并交给 PTB 处理。"""
        try:
            ptb_app = request.app.state.ptb_app
            update_data = await request.json()
            update = Update.de_json(data=update_data, bot=ptb_app.bot)
            await ptb_app.process_update(update)
            return Response(status_code=200)
        except Exception as e:
            logger.error(f"处理 Webhook 更新时发生严重错误: {e}", exc_info=True)
            return Response(status_code=500)

    logger.info("🔥 准备启动 Uvicorn 服务器...")
    uvicorn.run(fastapi_app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    if not all([TOKEN, RENDER_URL]):
        logger.critical("❌ 致命错误: 环境变量 TELEGRAM_BOT_TOKEN 或 RENDER_EXTERNAL_URL 未设置。程序终止。")
    else:
        main()
