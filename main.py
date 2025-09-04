import logging
import uvicorn
from os import environ
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram.error import TimedOut, BadRequest
from fastapi import FastAPI, Request, Response

from database import init_pool, create_tables
from handlers.reputation import (
    handle_nomination, button_handler as reputation_button_handler,
    show_reputation_summary, show_reputation_details, show_reputation_voters,
    show_voters_menu, handle_username_query
)
from handlers.leaderboard import show_leaderboard, clear_leaderboard_cache
from handlers.admin import (
    is_admin, god_mode_command, settings_menu, 
    tags_panel, add_tag_prompt, add_multiple_tags_prompt, remove_tag_menu, remove_tag_confirm, list_all_tags,
    permissions_panel, add_admin_prompt, list_admins, remove_admin_menu, remove_admin_confirm,
    system_settings_panel, set_setting_prompt, set_start_message_prompt,
    leaderboard_panel, remove_from_leaderboard_prompt,
    process_admin_input, show_all_commands
)
from handlers.favorites import my_favorites, handle_favorite_button
from handlers.stats import show_system_stats
from handlers.erasure import handle_erasure_functions

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
        from database import db_transaction
        creator_id = int(CREATOR_ID)
        async with db_transaction() as conn:
            await conn.execute("INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE", creator_id)
        logger.info(f"✅ (启动流程) 创世神 {creator_id} 已被自动分封为第一守护者。")
    except Exception as e:
        logger.error(f"❌ (启动流程) 分封创世神时发生错误: {e}", exc_info=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button: bool = False):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from database import get_system_setting
    
    user_id = update.effective_user.id
    user_is_admin = await is_admin(user_id)
    
    # 从数据库获取自定义的开始消息
    start_message = await get_system_setting('start_message')
    if not start_message:
        start_message = (
            "我是 **神谕者 (The Oracle)**，洞察世间一切信誉的实体。\n\n"
            "**聆听神谕:**\n"
            "1. 在群聊中直接 `@某人` 或发送 `查询 @某人`，即可向我求问关于此人的神谕之卷。\n"
            "2. 使用下方按钮，可窥探时代群像或管理你的星盘。"
        )
    
    text = start_message
    
    if user_is_admin:
        text += "\n\n你，是守护者。拥有进入 `🌌 时空枢纽` 的权限。"
    
    keyboard = [
        [InlineKeyboardButton("🏆 英灵殿", callback_data="leaderboard_top_tagselect_1"),
         InlineKeyboardButton("☠️ 放逐深渊", callback_data="leaderboard_bottom_tagselect_1")],
        [InlineKeyboardButton("🌟 我的星盘", callback_data="show_my_favorites"),
         InlineKeyboardButton("📊 神谕数据", callback_data="show_system_stats")]
    ]
    if user_is_admin:
        keyboard.append([InlineKeyboardButton("🌌 时空枢纽", callback_data="admin_settings_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_content = {'text': text, 'reply_markup': reply_markup, 'parse_mode': 'Markdown'}
    
    if from_button or (update.callback_query and update.callback_query.data == 'back_to_help'):
        await update.callback_query.edit_message_text(**message_content)
    else:
        await update.message.reply_text(**message_content)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await help_command(update, context)

async def all_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except TimedOut:
        logger.warning(f"对 query {query.id} 的响应超时。")
    except Exception as e:
        logger.error(f"对 query {query.id} 的响应时发生未知错误: {e}", exc_info=True)

    data = query.data
    try:
        if data.startswith("admin_"):
            if data == "admin_settings_menu": await settings_menu(update, context)
            elif data == "admin_panel_tags": await tags_panel(update, context)
            elif data == "admin_tags_add_recommend_prompt": await add_tag_prompt(update, context, "recommend")
            elif data == "admin_tags_add_block_prompt": await add_tag_prompt(update, context, "block")
            elif data == "admin_tags_add_multiple_prompt": await add_multiple_tags_prompt(update, context)
            elif data.startswith("admin_tags_remove_menu_"): await remove_tag_menu(update, context, int(data.split("_")[-1]))
            elif data.startswith("admin_tags_remove_confirm_"): await remove_tag_confirm(update, context, int(data.split("_")[-2]), int(data.split("_")[-1]))
            elif data == "admin_tags_list": await list_all_tags(update, context)
            elif data == "admin_panel_permissions": await permissions_panel(update, context)
            elif data == "admin_perms_add_prompt": await add_admin_prompt(update, context)
            elif data == "admin_perms_list": await list_admins(update, context)
            elif data == "admin_perms_remove_menu": await remove_admin_menu(update, context)
            elif data.startswith("admin_perms_remove_confirm_"): await remove_admin_confirm(update, context, int(data.split("_")[-1]))
            elif data == "admin_panel_system": await system_settings_panel(update, context)
            elif data == "admin_system_set_start_message": await set_start_message_prompt(update, context)
            elif data.startswith("admin_system_set_prompt_"): await set_setting_prompt(update, context, data[len("admin_system_set_prompt_"):])
            elif data == "admin_leaderboard_panel": await leaderboard_panel(update, context)
            elif data == "admin_leaderboard_remove_prompt": await remove_from_leaderboard_prompt(update, context)
            elif data == "admin_leaderboard_clear_cache": 
                clear_leaderboard_cache()
                await update.callback_query.answer("✅ 排行榜缓存已清空", show_alert=True)
            elif data == "admin_show_commands": await show_all_commands(update, context)
        
        elif data.startswith("rep_"):
            if data.startswith("rep_detail_"): await show_reputation_details(update, context)
            elif data.startswith("rep_summary_"): await show_reputation_summary(update, context)
            elif data.startswith("rep_voters_menu_"): await show_voters_menu(update, context)
            elif data.startswith("rep_voters_"): await show_reputation_voters(update, context)
        
        elif data.startswith("leaderboard_"):
            await show_leaderboard(update, context)
        
        elif data == "show_my_favorites": await my_favorites(update, context)
        elif data == "show_system_stats": await show_system_stats(update, context)
        elif data.startswith("query_fav"): await handle_favorite_button(update, context)
        elif data == "back_to_help": await help_command(update, context, from_button=True)
        elif data.startswith(("vote_", "tag_")): await reputation_button_handler(update, context)
        elif data.startswith("erasure_"): await handle_erasure_functions(update, context)
        elif data == "noop": pass
        else: logger.warning(f"收到未知的回调数据: {data}")
    except Exception as e:
        logger.error(f"处理按钮回调 {data} 时发生错误: {e}", exc_info=True)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'next_action' in context.user_data:
        del context.user_data['next_action']
        await update.message.reply_text("操作已取消。")
    else:
        await update.message.reply_text("当前没有正在进行的操作。")

async def commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await is_admin(user_id):
        await show_all_commands(update, context, from_command=True)
    else:
        await update.message.reply_text("此命令仅管理员可用")

ptb_app = Application.builder().token(TOKEN).post_init(grant_creator_admin_privileges).build()

ptb_app.add_handler(CommandHandler("godmode", god_mode_command))
ptb_app.add_handler(CommandHandler(["start", "help"], start_command))
ptb_app.add_handler(CommandHandler("cancel", cancel_command))
ptb_app.add_handler(CommandHandler("myfavorites", my_favorites))
ptb_app.add_handler(CommandHandler("commands", commands_command))
ptb_app.add_handler(CallbackQueryHandler(all_button_handler))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, process_admin_input))

# 增强的用户查询支持 - 私聊中也可以查询
ptb_app.add_handler(MessageHandler(
    filters.Regex(r'^查询\s+@(\w{5,})$') & ~filters.COMMAND,
    handle_username_query
))

# 用 MessageHandler 替代已不支持的 RegexHandler
# 原有的直接@用户功能 - 仅在群聊中
ptb_app.add_handler(MessageHandler(
    filters.Regex(r'(?:@(\w{5,}))|(?:查询\s*@(\w{5,}))') & ~filters.COMMAND & filters.ChatType.GROUPS,
    handle_nomination
))

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 FastAPI 应用启动，正在初始化...")
    await init_pool()
    await create_tables()
    await ptb_app.bot.delete_webhook(drop_pending_updates=True)
    await ptb_app.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES)
    async with ptb_app:
        await ptb_app.start()
        logger.info("✅ 神谕者已降临。")
        yield
        logger.info("🔌 神谕者正在回归沉寂...")
        await ptb_app.stop()

def main():
    fastapi_app = FastAPI(lifespan=lifespan)
    @fastapi_app.get("/", include_in_schema=False)
    async def health_check():
        return {"status": "ok", "message": "The Oracle is listening."}
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
