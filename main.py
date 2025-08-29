import logging
import uvicorn
from os import environ
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from fastapi import FastAPI, Request, Response

# --- 导入所有模块和处理器 ---
from database import init_pool, create_tables, db_cursor
from handlers.reputation import handle_nomination, button_handler as reputation_button_handler
from handlers.leaderboard import get_top_board, get_bottom_board, show_leaderboard
from handlers.admin import set_admin, list_tags, add_tag, remove_tag
# 核心修复：导入全新的收藏夹处理器
from handlers.favorites import my_favorites, handle_favorite_button

# --- 日志和环境变量设置 ---
load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = environ.get("TELEGRAM_BOT_TOKEN")
PORT = int(environ.get('PORT', '10000'))
RENDER_URL = environ.get('RENDER_EXTERNAL_URL')
WEBHOOK_URL = f"{RENDER_URL}/{TOKEN}" if RENDER_URL else None
CREATOR_ID = environ.get("CREATOR_ID")

# --- 核心业务逻辑 (Telegram 命令处理) ---

async def grant_creator_admin_privileges(app: Application):
    if not CREATOR_ID: return
    try:
        creator_id = int(CREATOR_ID)
        async with db_cursor() as cur:
            await cur.execute("INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE", creator_id)
        logger.info(f"✅ 创世神 {creator_id} 已被自动授予管理员权限。")
    except Exception as e:
        logger.error(f"❌ 授予创世神权限时发生错误: {e}", exc_info=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_cursor() as cur:
        await cur.execute("INSERT INTO users (id) VALUES ($1) ON CONFLICT DO NOTHING", update.effective_user.id)
    await update.message.reply_text("你好！我是万物信誉机器人。使用 /help 查看所有命令。")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin_user = False
    try:
        async with db_cursor() as cur:
            await cur.execute("INSERT INTO users (id) VALUES ($1) ON CONFLICT DO NOTHING", update.effective_user.id)
            user_data = await cur.fetchrow("SELECT is_admin FROM users WHERE id = $1", update.effective_user.id)
            if user_data: is_admin_user = user_data['is_admin']
    except Exception as e: logger.error(f"查询用户权限时出错: {e}")

    # 核心修复：将 /myfavorites 加入帮助信息
    user_help = (
        "**用户命令:**\n"
        "`查询 @任意符号` - 查询某个符号的信誉并发起评价。\n"
        "`/top` 或 `/红榜` - 查看推荐排行榜。\n"
        "`/bottom` 或 `/黑榜` - 查看拉黑排行榜。\n"
        "`/myfavorites` - 查看你的个人收藏夹（私聊发送）。\n"
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
    await query.answer()

    data = query.data.split('_')
    action_type = data[0]

    try:
        if action_type in ["vote", "tag"]:
            await reputation_button_handler(update, context)
        elif action_type == "leaderboard":
            if data[1] == "noop": return
            await show_leaderboard(update, context, board_type=data[1], page=int(data[2]))
        # 核心修复：将 fav 和 query_fav 类型的按钮点击，都交给收藏夹处理器
        elif action_type in ["fav", "query"]:
            await handle_favorite_button(update, context)
        else:
            logger.warning(f"收到未知的按钮回调数据: {query.data}")
    except Exception as e:
        logger.error(f"处理按钮回调 {query.data} 时发生错误: {e}", exc_info=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 应用的生命周期管理器。"""
    logger.info("🚀 FastAPI 应用启动，正在初始化...")
    await init_pool()
    await create_tables()
    
    ptb_app = Application.builder().token(TOKEN).build()
    
    # --- 注册所有处理器 ---
    ptb_app.add_handler(MessageHandler(filters.Regex('^查询'), handle_nomination))
    ptb_app.add_handler(CommandHandler("start", start))
    ptb_app.add_handler(CommandHandler("help", help_command))
    ptb_app.add_handler(CommandHandler(["top", "红榜"], get_top_board))
    ptb_app.add_handler(CommandHandler(["bottom", "黑榜"], get_bottom_board))
    # 核心修复：注册 /myfavorites 命令处理器
    ptb_app.add_handler(CommandHandler("myfavorites", my_favorites))
    ptb_app.add_handler(CommandHandler("setadmin", set_admin))
    ptb_app.add_handler(CommandHandler("listtags", list_tags))
    ptb_app.add_handler(CommandHandler("addtag", add_tag))
    ptb_app.add_handler(CommandHandler("removetag", remove_tag))
    ptb_app.add_handler(CallbackQueryHandler(all_button_handler))
    
    await ptb_app.initialize()
    await ptb_app.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    await grant_creator_admin_privileges(ptb_app)
    await ptb_app.start()
    app.state.ptb_app = ptb_app
    logger.info("✅ PTB 应用已在后台启动。")
    yield
    logger.info("🔌 FastAPI 应用关闭，正在停止 PTB...")
    await app.state.ptb_app.stop()
    await app.state.ptb_app.shutdown()

def main():
    """主程序入口。"""
    fastapi_app = FastAPI(lifespan=lifespan)
    @fastapi_app.post(f"/{TOKEN}", include_in_schema=False)
    async def process_telegram_update(request: Request):
        try:
            await request.app.state.ptb_app.update_queue.put(Update.de_json(await request.json(), request.app.state.ptb_app.bot))
            return Response(status_code=200)
        except Exception as e:
            logger.error(f"处理 Webhook 更新时发生严重错误: {e}", exc_info=True)
            return Response(status_code=500)
    uvicorn.run(fastapi_app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    if not all([TOKEN, RENDER_URL]):
        logger.critical("❌ 致命错误: 环境变量 TELEGRAM_BOT_TOKEN 或 RENDER_EXTERNAL_URL 未设置。")
    else:
        main()
