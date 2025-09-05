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
from telegram.constants import ParseMode
from telegram.error import TimedOut, BadRequest
from fastapi import FastAPI, Request, Response

# 数据库和工具
from database import init_pool, close_pool, create_tables, is_admin, get_setting, db_execute, db_fetch_one
from handlers.utils import schedule_message_deletion

# 处理器导入
from handlers.reputation import (
    handle_nomination, 
    button_handler as reputation_button_handler,
    show_reputation_summary, 
    show_reputation_details, 
    show_reputation_voters,
    show_voters_menu, 
    handle_username_query,
    handle_vote_comment,
    handle_vote_submit,
    handle_comment_input
)
from handlers.leaderboard import show_leaderboard, clear_leaderboard_cache
from handlers.admin import (
    god_mode_command, 
    settings_menu, 
    process_admin_input,
    tags_panel, 
    permissions_panel, 
    system_settings_panel, 
    leaderboard_panel,
    add_tag_prompt, 
    remove_tag_menu, 
    remove_tag_confirm, 
    list_all_tags,
    add_admin_prompt, 
    list_admins, 
    remove_admin_menu, 
    remove_admin_confirm,
    execute_admin_removal, # 确保这些也导入
    execute_tag_deletion,
    set_setting_prompt, 
    set_start_message_prompt, 
    show_all_commands,
    remove_from_leaderboard_prompt,
    selective_remove_menu,
    confirm_user_removal,
    execute_user_removal
)
from handlers.favorites import my_favorites, handle_favorite_button
from handlers.stats import show_system_stats
from handlers.erasure import handle_erasure_functions

# 配置
load_dotenv()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = environ.get("TELEGRAM_BOT_TOKEN")
PORT = int(environ.get("PORT", "10000"))
RENDER_URL = environ.get("RENDER_EXTERNAL_URL")
WEBHOOK_URL = f"{RENDER_URL}/{TOKEN}" if RENDER_URL else None
CREATOR_ID = environ.get("CREATOR_ID")

# --- 核心命令和处理器 ---

async def grant_creator_admin_privileges():
    """在启动时为创建者授予管理员权限"""
    if not CREATOR_ID:
        logger.info("未设置CREATOR_ID，跳过创建者权限授予")
        return
    try:
        creator_id = int(CREATOR_ID)
        await db_execute(
            "INSERT INTO users (id, first_name, is_admin) VALUES ($1, 'Creator', TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE",
            creator_id
        )
        logger.info(f"✅ 创建者 {creator_id} 已被检查并授予管理员权限")
    except ValueError:
        logger.error("CREATOR_ID 必须是数字")
    except Exception as e:
        logger.error(f"❌ 授予创建者管理员权限失败: {e}", exc_info=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button: bool = False):
    """显示帮助和主菜单 (美化版 - 2x2布局)"""
    user_id = update.effective_user.id
    user_is_admin = await is_admin(user_id)
    
    start_message = await get_setting('start_message')
    if not start_message:
        start_message = (
            "**我是神谕者 (The Oracle)，洞察世间一切信誉的实体。**\n\n"
            "在命运的织网中，每个灵魂的声誉都如星辰般闪耀或黯淡。向我求问，我将为你揭示真相之卷。\n\n"
            "**聆听神谕:**\n"
            "• 在群聊中 `@某人`，即可窥探其命运轨迹。\n"
            "• 使用下方按钮，可遨游数据星海或管理你的羁绊。"
        )
    text = start_message
    if user_is_admin:
        text += "\n\n✨ *你的意志即是法则，守护者。时空枢纽已为你开启。*"
    
    keyboard = [
        [
            InlineKeyboardButton("🏆 好评榜", callback_data="leaderboard_top_tagselect_1"),
            InlineKeyboardButton("☠️ 差评榜", callback_data="leaderboard_bottom_tagselect_1")
        ],
        [
            InlineKeyboardButton("🌟 我的收藏", callback_data="show_my_favorites"),
            InlineKeyboardButton("📊 系统统计", callback_data="show_system_stats")
        ],
        [InlineKeyboardButton("🔥 数据抹除", callback_data="erasure_menu")]
    ]
    if user_is_admin:
        keyboard.append([InlineKeyboardButton("🌌 管理面板", callback_data="admin_settings_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_content = {'text': text, 'reply_markup': reply_markup, 'parse_mode': ParseMode.MARKDOWN}
    
    sent_message = None
    query = update.callback_query
    
    if from_button or (query and query.data == 'back_to_help'):
        target_message = query.message
        try:
            # 检查内容是否变化，避免不必要的API调用
            if target_message.text == text and target_message.reply_markup == reply_markup:
                await query.answer()
            else:
                await query.edit_message_text(**message_content)
            sent_message = target_message
        except BadRequest as e:
            if "message is not modified" in e.message:
                await query.answer() # 静默处理
            else:
                logger.error(f"编辑主菜单时出错: {e}")
            sent_message = target_message
        except Exception as e:
            logger.error(f"编辑主菜单时发生未知错误: {e}")
            await query.answer("发生错误，请重试")
    else:
        sent_message = await update.message.reply_text(**message_content)

    if sent_message:
        await schedule_message_deletion(context, sent_message.chat.id, sent_message.message_id)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理/start命令，调用主菜单"""
    await help_command(update, context)

async def all_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """【完整版】统一的按钮回调处理器"""
    query = update.callback_query
    try: await query.answer()
    except (TimedOut, Exception): pass
    
    data = query.data
    user_id = update.effective_user.id
    
    # 每个交互都会重置消息的删除计时器
    await schedule_message_deletion(context, query.message.chat.id, query.message.message_id)
    
    try:
        # === 管理员功能 ===
        if data.startswith("admin_"):
            if not await is_admin(user_id): await query.answer("❌ 权限不足", show_alert=True); return
            
            if data == "admin_settings_menu": await settings_menu(update, context)
            elif data == "admin_panel_tags": await tags_panel(update, context)
            elif data == "admin_tags_add_recommend_prompt": await add_tag_prompt(update, context, "recommend")
            elif data == "admin_tags_add_block_prompt": await add_tag_prompt(update, context, "block")
            elif data.startswith("admin_tags_remove_menu_"): await remove_tag_menu(update, context, int(data.split("_")[-1]))
            elif data.startswith("admin_tags_remove_confirm_"): await remove_tag_confirm(update, context, int(data.split("_")[-2]), int(data.split("_")[-1]))
            elif data.startswith("admin_tag_delete_"): await execute_tag_deletion(update, context, int(data.split("_")[-1]))
            elif data == "admin_tags_list": await list_all_tags(update, context)
            elif data == "admin_panel_permissions": await permissions_panel(update, context)
            elif data == "admin_perms_add_prompt": await add_admin_prompt(update, context)
            elif data == "admin_perms_list": await list_admins(update, context)
            elif data == "admin_perms_remove_menu": await remove_admin_menu(update, context)
            elif data.startswith("admin_perms_remove_confirm_"): await remove_admin_confirm(update, context, int(data.split("_")[-1]))
            elif data.startswith("admin_remove_admin_"): await execute_admin_removal(update, context, int(data.split("_")[-1]))
            elif data == "admin_panel_system": await system_settings_panel(update, context)
            elif data == "admin_system_set_start_message": await set_start_message_prompt(update, context)
            elif data.startswith("admin_system_set_prompt_"): await set_setting_prompt(update, context, data.replace("admin_system_set_prompt_", ""))
            elif data == "admin_leaderboard_panel": await leaderboard_panel(update, context)
            elif data == "admin_leaderboard_remove_prompt": await remove_from_leaderboard_prompt(update, context)
            elif data == "admin_leaderboard_clear_cache": clear_leaderboard_cache(); await query.answer("✅ 排行榜缓存已清除", show_alert=True)
            elif data == "admin_selective_remove_menu": await selective_remove_menu(update, context, "top", 1)
            elif data.startswith("admin_selective_remove_"): p = data.split("_"); await selective_remove_menu(update, context, p[3], int(p[4]))
            elif data.startswith("admin_confirm_remove_user_"): p = data.split("_"); await confirm_user_removal(update, context, int(p[4]), p[5], int(p[6]))
            elif data.startswith("admin_remove_user_"): p = data.split("_"); await execute_user_removal(update, context, int(p[4]), p[3], p[5], int(p[6]))
            elif data == "admin_show_commands": await show_all_commands(update, context)
        # === 声誉功能 ===
        elif data.startswith("rep_"):
            if data.startswith("rep_detail_"): await show_reputation_details(update, context)
            elif data.startswith("rep_summary_"): await show_reputation_summary(update, context)
            elif data.startswith("rep_voters_menu_"): await show_voters_menu(update, context)
            elif data.startswith("rep_voters_"): await show_reputation_voters(update, context)
        # === 其他核心功能 ===
        elif data.startswith("leaderboard_"): await show_leaderboard(update, context)
        elif data == "show_my_favorites": await my_favorites(update, context)
        elif data.startswith("query_fav"): await handle_favorite_button(update, context)
        elif data == "show_system_stats": await show_system_stats(update, context)
        elif data.startswith("erasure_"): await handle_erasure_functions(update, context)
        elif data.startswith(("vote_", "tag_", "toggle_favorite_")):
            if data.startswith("vote_comment_"): await handle_vote_comment(update, context)
            elif data.startswith("vote_submit_"): await handle_vote_submit(update, context)
            else: await reputation_button_handler(update, context)
        # === 导航 ===
        elif data == "back_to_help": await help_command(update, context, from_button=True)
        elif data == "noop": pass # 空操作，只为了重置计时器
        else: logger.warning(f"未知的回调数据: {data}")
    except Exception as e: logger.error(f"处理按钮回调时出错 {data}: {e}", exc_info=True)

async def private_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理私聊文本消息"""
    if await handle_comment_input(update, context): return
    if await is_admin(update.effective_user.id):
        await process_admin_input(update, context)
    else:
        await update.message.reply_text("我不明白您的意思。请使用主菜单的功能按钮。")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消当前操作"""
    for key in ['next_action', 'comment_input', 'current_vote']:
        context.user_data.pop(key, None)
    await update.message.reply_text("✅ 操作已取消")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理错误"""
    logger.error(f"异常由更新引发: {context.error}", exc_info=context.error)

# --- 启动与生命周期 ---
ptb_app = Application.builder().token(TOKEN).build()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI生命周期管理"""
    logger.info("🚀 启动神谕者机器人...")
    await init_pool()
    await create_tables()
    await grant_creator_admin_privileges()
    
    async with ptb_app:
        await ptb_app.initialize()
        await ptb_app.start()
        # 在生产环境，通常在启动时设置一次 webhook
        if RENDER_URL:
            await ptb_app.bot.delete_webhook(drop_pending_updates=True)
            await ptb_app.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES)
            logger.info(f"✅ Webhook已设置: {WEBHOOK_URL}")
        
        logger.info("✅ 神谕者已就绪并开始监听")
        yield # FastAPI 服务在此运行
        
    logger.info("🔌 关闭神谕者机器人...")
    if ptb_app.running:
        await ptb_app.stop()
    await close_pool()
    logger.info("数据库连接池已关闭")

def main():
    """主函数，配置并启动应用"""
    if not TOKEN:
        logger.critical("❌ TELEGRAM_BOT_TOKEN 环境变量未设置")
        return
    
    fastapi_app = FastAPI(title="神谕者机器人", version="2.3.0", lifespan=lifespan)
    
    # --- 【完整】注册所有处理器 ---
    ptb_app.add_error_handler(error_handler)
    
    # 命令处理器
    ptb_app.add_handler(CommandHandler(["start", "help"], start_command))
    ptb_app.add_handler(CommandHandler("cancel", cancel_command))
    ptb_app.add_handler(CommandHandler("myfavorites", my_favorites))
    ptb_app.add_handler(CommandHandler("godmode", god_mode_command))
    
    # 回调查询处理器 (所有按钮点击都由它处理)
    ptb_app.add_handler(CallbackQueryHandler(all_button_handler))
    
    # 消息处理器
    ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, private_text_handler))
    ptb_app.add_handler(MessageHandler(filters.Regex(r'(?:@(\w{5,}))|(?:查询\s*@(\w{5,}))') & ~filters.COMMAND & filters.ChatType.GROUPS, handle_nomination))
    ptb_app.add_handler(MessageHandler(filters.Regex(r'^查询\s+@(\w{5,})$') & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_username_query))
    
    # Webhook 路由
    @fastapi_app.post(f"/{TOKEN}", include_in_schema=False)
    async def process_telegram_update(request: Request):
        try:
            update = Update.de_json(await request.json(), ptb_app.bot)
            await ptb_app.process_update(update)
            return Response(status_code=200)
        except Exception as e:
            logger.error(f"处理Webhook时出错: {e}", exc_info=True)
            return Response(status_code=500)
    
    logger.info(f"🌐 启动FastAPI服务器，端口: {PORT}")
    uvicorn.run(fastapi_app, host="0.0.0.0", port=PORT, log_level="info")

if __name__ == "__main__":
    main()
