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
from telegram.error import TimedOut
from fastapi import FastAPI, Request, Response

from database import init_pool, create_tables, is_admin, get_setting
from handlers.reputation import (
    handle_nomination, button_handler as reputation_button_handler,
    show_reputation_summary, show_reputation_details, show_reputation_voters,
    show_voters_menu, handle_username_query
)
from handlers.leaderboard import show_leaderboard, clear_leaderboard_cache
from handlers.admin import (
    god_mode_command, settings_menu, process_admin_input,
    tags_panel, permissions_panel, system_settings_panel, leaderboard_panel,
    add_tag_prompt, remove_tag_menu, remove_tag_confirm, list_all_tags,
    add_admin_prompt, list_admins, remove_admin_menu, remove_admin_confirm,
    set_setting_prompt, set_start_message_prompt, show_all_commands,
    remove_from_leaderboard_prompt, add_motto_prompt, list_mottos
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
    """给创建者管理员权限"""
    if not CREATOR_ID:
        return
    try:
        from database import db_execute
        creator_id = int(CREATOR_ID)
        await db_execute(
            "INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE",
            creator_id
        )
        logger.info(f"✅ 创建者 {creator_id} 已获得管理员权限")
    except Exception as e:
        logger.error(f"❌ 授予创建者管理员权限失败: {e}", exc_info=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button: bool = False):
    """显示帮助和主菜单"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
    user_id = update.effective_user.id
    user_is_admin = await is_admin(user_id)
    
    # 从数据库获取自定义的开始消息
    start_message = await get_setting('start_message')
    if not start_message:
        start_message = (
            "我是 **神谕者 (The Oracle)**，洞察世间一切信誉的实体。\n\n"
            "**聆听神谕:**\n"
            "1. 在群聊中直接 `@某人` 或发送 `查询 @某人`，即可向我求问关于此人的神谕之卷。\n"
            "2. 使用下方按钮，可窥探时代群像或管理你的星盘。"
        )
    
    text = start_message
    
    if user_is_admin:
        text += "\n\n✨ 你是守护者，可使用管理功能。"
    
    keyboard = [
        [
            InlineKeyboardButton("🏆 英灵殿", callback_data="leaderboard_top_tagselect_1"),
            InlineKeyboardButton("☠️ 放逐深渊", callback_data="leaderboard_bottom_tagselect_1")
        ],
        [
            InlineKeyboardButton("🌟 我的星盘", callback_data="show_my_favorites"),
            InlineKeyboardButton("📊 神谕数据", callback_data="show_system_stats")
        ],
        [
            InlineKeyboardButton("🔥 抹除室", callback_data="erasure_menu")
        ]
    ]
    
    if user_is_admin:
        keyboard.append([InlineKeyboardButton("🌌 时空枢纽", callback_data="admin_settings_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_content = {
        'text': text, 
        'reply_markup': reply_markup, 
        'parse_mode': 'Markdown'
    }
    
    if from_button or (update.callback_query and update.callback_query.data == 'back_to_help'):
        await update.callback_query.edit_message_text(**message_content)
    else:
        await update.message.reply_text(**message_content)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理/start命令"""
    await help_command(update, context)

async def all_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """统一的按钮处理器"""
    query = update.callback_query
    
    try:
        await query.answer()
    except TimedOut:
        logger.warning(f"查询 {query.id} 响应超时")
    except Exception as e:
        logger.error(f"响应查询时出错: {e}")

    data = query.data
    
    try:
        # 管理员功能
        if data.startswith("admin_"):
            if data == "admin_settings_menu":
                await settings_menu(update, context)
            elif data == "admin_panel_tags":
                await tags_panel(update, context)
            elif data == "admin_tags_add_recommend_prompt":
                await add_tag_prompt(update, context, "recommend")
            elif data == "admin_tags_add_block_prompt":
                await add_tag_prompt(update, context, "block")
            elif data.startswith("admin_tags_remove_menu_"):
                page = int(data.split("_")[-1])
                await remove_tag_menu(update, context, page)
            elif data.startswith("admin_tags_remove_confirm_"):
                parts = data.split("_")
                tag_id = int(parts[-2])
                page = int(parts[-1])
                await remove_tag_confirm(update, context, tag_id, page)
            elif data == "admin_tags_list":
                await list_all_tags(update, context)
            elif data == "admin_panel_permissions":
                await permissions_panel(update, context)
            elif data == "admin_perms_add_prompt":
                await add_admin_prompt(update, context)
            elif data == "admin_perms_list":
                await list_admins(update, context)
            elif data == "admin_perms_remove_menu":
                await remove_admin_menu(update, context)
            elif data.startswith("admin_perms_remove_confirm_"):
                admin_id = int(data.split("_")[-1])
                await remove_admin_confirm(update, context, admin_id)
            elif data == "admin_panel_system":
                await system_settings_panel(update, context)
            elif data == "admin_system_set_start_message":
                await set_start_message_prompt(update, context)
            elif data.startswith("admin_system_set_prompt_"):
                key = data.replace("admin_system_set_prompt_", "")
                await set_setting_prompt(update, context, key)
            elif data == "admin_leaderboard_panel":
                await leaderboard_panel(update, context)
            elif data == "admin_leaderboard_remove_prompt":
                await remove_from_leaderboard_prompt(update, context)
            elif data == "admin_leaderboard_clear_cache":
                clear_leaderboard_cache()
                await query.answer("✅ 排行榜缓存已清除", show_alert=True)
            elif data == "admin_show_commands":
                await show_all_commands(update, context)
            elif data == "admin_add_motto_prompt":
                await add_motto_prompt(update, context)
            elif data == "admin_list_mottos":
                await list_mottos(update, context)
        
        # 声誉相关
        elif data.startswith("rep_"):
            if data.startswith("rep_detail_"):
                await show_reputation_details(update, context)
            elif data.startswith("rep_summary_"):
                await show_reputation_summary(update, context)
            elif data.startswith("rep_voters_menu_"):
                await show_voters_menu(update, context)
            elif data.startswith("rep_voters_"):
                await show_reputation_voters(update, context)
        
        # 排行榜
        elif data.startswith("leaderboard_"):
            await show_leaderboard(update, context)
        
        # 其他功能
        elif data == "show_my_favorites":
            await my_favorites(update, context)
        elif data == "show_system_stats":
            await show_system_stats(update, context)
        elif data.startswith("query_fav"):
            await handle_favorite_button(update, context)
        elif data == "back_to_help":
            await help_command(update, context, from_button=True)
        elif data.startswith(("vote_", "tag_")):
            await reputation_button_handler(update, context)
        elif data.startswith("erasure_"):
            await handle_erasure_functions(update, context)
        elif data == "noop":
            pass
        else:
            logger.warning(f"未知的回调数据: {data}")
    
    except Exception as e:
        logger.error(f"处理按钮回调时出错 {data}: {e}", exc_info=True)
        try:
            await query.answer("操作失败，请稍后再试", show_alert=True)
        except:
            pass

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消当前操作"""
    if 'next_action' in context.user_data:
        del context.user_data['next_action']
        await update.message.reply_text("✅ 操作已取消")
    else:
        await update.message.reply_text("ℹ️ 当前没有进行中的操作")

async def commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示所有命令（仅管理员）"""
    user_id = update.effective_user.id
    if await is_admin(user_id):
        await show_all_commands(update, context, from_command=True)
    else:
        await update.message.reply_text("此命令仅管理员可用")

# 创建应用
ptb_app = Application.builder().token(TOKEN).post_init(grant_creator_admin_privileges).build()

# 添加处理器
ptb_app.add_handler(CommandHandler("godmode", god_mode_command))
ptb_app.add_handler(CommandHandler(["start", "help"], start_command))
ptb_app.add_handler(CommandHandler("cancel", cancel_command))
ptb_app.add_handler(CommandHandler("myfavorites", my_favorites))
ptb_app.add_handler(CommandHandler("commands", commands_command))
ptb_app.add_handler(CallbackQueryHandler(all_button_handler))

# 管理员文本输入处理
ptb_app.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
    process_admin_input
))

# 群聊中的@用户处理
ptb_app.add_handler(MessageHandler(
    filters.Regex(r'(?:@(\w{5,}))|(?:查询\s*@(\w{5,}))') & ~filters.COMMAND & filters.ChatType.GROUPS,
    handle_nomination
))

# 私聊中的查询处理
ptb_app.add_handler(MessageHandler(
    filters.Regex(r'^查询\s+@(\w{5,})$') & ~filters.COMMAND & filters.ChatType.PRIVATE,
    handle_username_query
))

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI生命周期管理"""
    logger.info("🚀 启动神谕者...")
    await init_pool()
    await create_tables()
    await ptb_app.bot.delete_webhook(drop_pending_updates=True)
    await ptb_app.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES)
    async with ptb_app:
        await ptb_app.start()
        logger.info("✅ 神谕者已就绪")
        yield
        logger.info("🔌 关闭神谕者...")
        await ptb_app.stop()

def main():
    """主函数"""
    fastapi_app = FastAPI(lifespan=lifespan)
    
    @fastapi_app.get("/", include_in_schema=False)
    async def health_check():
        return {"status": "ok", "message": "神谕者正在运行"}
    
    @fastapi_app.post(f"/{TOKEN}", include_in_schema=False)
    async def process_telegram_update(request: Request):
        try:
            update = Update.de_json(await request.json(), ptb_app.bot)
            await ptb_app.process_update(update)
            return Response(status_code=200)
        except Exception as e:
            logger.error(f"处理Webhook时出错: {e}", exc_info=True)
            return Response(status_code=500)
    
    uvicorn.run(fastapi_app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    if not all([TOKEN, RENDER_URL]):
        logger.critical("❌ 环境变量 TELEGRAM_BOT_TOKEN 或 RENDER_EXTERNAL_URL 未设置")
    else:
        main()
