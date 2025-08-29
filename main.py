import logging
import uvicorn
from os import environ
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from fastapi import FastAPI, Request, Response

from database import init_pool, create_tables, db_transaction
from handlers.reputation import handle_nomination
from handlers.leaderboard import show_leaderboard
# --- “神权进化”：导入新的 admin handler ---
from handlers.admin import (
    is_admin, god_mode_command, settings_menu, 
    tags_panel, add_tag_prompt, remove_tag_menu, remove_tag_confirm, process_admin_input
)
from handlers.favorites import my_favorites, handle_favorite_button

# --- (其余代码保持不变，直到 all_button_handler) ---
load_dotenv()
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
TOKEN = environ.get("TELEGRAM_BOT_TOKEN")
PORT = int(environ.get("PORT", "10000"))
RENDER_URL = environ.get("RENDER_EXTERNAL_URL")
WEBHOOK_URL = f"{RENDER_URL}/{TOKEN}" if RENDER_URL else None
CREATOR_ID = environ.get("CREATOR_ID")

async def grant_creator_admin_privileges(app: Application):
    if not CREATOR_ID: return
    try:
        creator_id = int(CREATOR_ID)
        async with db_transaction() as conn:
            await conn.execute("INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE", creator_id)
        logger.info(f"✅ (启动流程) 创世神 {creator_id} 已被自动授予管理员权限。")
    except Exception as e:
        logger.error(f"❌ (启动流程) 授予创世神权限时发生错误: {e}", exc_info=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button: bool = False):
    user_id = update.effective_user.id
    async with db_transaction() as conn:
        await conn.execute("INSERT INTO users (id) VALUES ($1) ON CONFLICT DO NOTHING", user_id)
    user_is_admin = await is_admin(user_id)
    text = "你好！我是万物信誉机器人。\n\n**使用方法:**\n1. 直接在群里发送 `查询 @任意符号` 来查看或评价一个符号。\n2. 使用下方的按钮来浏览排行榜或你的个人收藏。"
    if user_is_admin:
        text += ("\n\n--- *管理员面板* ---\n"
                 "请使用下方的 `⚙️ 世界设置` 按钮进入可视化管理面板。")
    keyboard = [[InlineKeyboardButton("🏆 红榜", callback_data="leaderboard_top_1")],
                [InlineKeyboardButton("☠️ 黑榜", callback_data="leaderboard_bottom_1")],
                [InlineKeyboardButton("⭐ 我的收藏", callback_data="show_my_favorites")]]
    if user_is_admin:
        keyboard.append([InlineKeyboardButton("⚙️ 世界设置", callback_data="admin_settings_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_content = {'text': text, 'reply_markup': reply_markup, 'parse_mode': 'Markdown'}
    if from_button or (update.callback_query and update.callback_query.data == 'back_to_help'):
        await update.callback_query.edit_message_text(**message_content)
    else:
        await update.message.reply_text(**message_content)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await help_command(update, context)

# --- “神权进化”核心：升级按钮处理器 ---
async def all_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    try:
        # 管理员面板路由
        if data == "admin_settings_menu": await settings_menu(update, context)
        elif data == "admin_panel_tags": await tags_panel(update, context)
        elif data == "admin_tags_add_recommend_prompt": await add_tag_prompt(update, context, "recommend")
        elif data == "admin_tags_add_block_prompt": await add_tag_prompt(update, context, "block")
        elif data.startswith("admin_tags_remove_menu_"):
            page = int(data.split("_")[-1])
            await remove_tag_menu(update, context, page)
        elif data.startswith("admin_tags_remove_confirm_"):
            _, _, _, _, tag_id, page = data.split("_")
            await remove_tag_confirm(update, context, int(tag_id), int(page))
        # 其他管理员面板占位符
        elif data.startswith("admin_panel_"):
            panel_target = data.split("_")[-1]
            await query.edit_message_text(f"您已进入 **{panel_target.capitalize()}** 管理模块。\n\n（此功能正在全力开发中，敬请期待！）", 
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ 返回神面板", callback_data="admin_settings_menu")]]))
        # 用户功能路由
        elif data.startswith("leaderboard_"):
            parts = data.split("_")
            if parts[1] == "noop": return
            await show_leaderboard(update, context, board_type=parts[1], page=int(parts[2]))
        elif data == "show_my_favorites": await my_favorites(update, context)
        elif data.startswith("query_fav"): await handle_favorite_button(update, context)
        elif data == "back_to_help": await help_command(update, context, from_button=True)
        elif data.startswith(("vote_", "tag_")):
            from handlers.reputation import button_handler as reputation_button_handler
            await reputation_button_handler(update, context)
        else: logger.warning(f"收到未知的按钮回调数据: {data}")
    except Exception as e:
        logger.error(f"处理按钮回调 {data} 时发生错误: {e}", exc_info=True)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clears any pending admin action."""
    if 'next_action' in context.user_data:
        del context.user_data['next_action']
        await update.message.reply_text("操作已取消。")
    else:
        await update.message.reply_text("当前没有正在进行的操作。")

# --- 应用程序设置 ---
ptb_app = Application.builder().token(TOKEN).post_init(grant_creator_admin_privileges).build()

# 核心命令
ptb_app.add_handler(CommandHandler("godmode", god_mode_command), group=-1)
ptb_app.add_handler(CommandHandler("start", start_command))
ptb_app.add_handler(CommandHandler("help", help_command))
ptb_app.add_handler(CommandHandler("top", lambda u, c: show_leaderboard(u, c, 'top', 1)))
ptb_app.add_handler(CommandHandler("bottom", lambda u, c: show_leaderboard(u, c, 'bottom', 1)))
ptb_app.add_handler(CommandHandler("myfavorites", my_favorites))
ptb_app.add_handler(CommandHandler("cancel", cancel_command)) # 新增取消命令

# 核心处理器
ptb_app.add_handler(CallbackQueryHandler(all_button_handler))
# group=1 表示它会优先于其他消息处理器被检查
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, process_admin_input), group=1)
ptb_app.add_handler(MessageHandler(filters.Regex("^查询"), handle_nomination), group=2)


# (FastAPI 和 main 函数保持不变)
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 FastAPI 应用启动，正在初始化...")
    await init_pool()
    await create_tables()
    # 在启动时清除所有旧的 webhook 设置
    await ptb_app.bot.delete_webhook(drop_pending_updates=True)
    await ptb_app.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES)
    async with ptb_app:
        await ptb_app.start()
        logger.info("✅ PTB 应用已在后台启动。")
        yield
        logger.info("🔌 FastAPI 应用关闭，正在停止 PTB...")
        await ptb_app.stop()

def main():
    fastapi_app = FastAPI(lifespan=lifespan)
    @fastapi_app.post(f"/{TOKEN}", include_in_schema=False)
    async def process_telegram_update(request: Request):
        try:
            update = Update.de_json(await request.json(), ptb_app.bot)
            await ptb_app.process_update(update)
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
