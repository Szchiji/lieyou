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
from telegram.error import TimedOut
from fastapi import FastAPI, Request, Response

# 数据库相关导入
from database import init_pool, close_pool, create_tables, is_admin, get_setting, db_execute, db_fetch_one

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

# 配置日志
load_dotenv()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 环境变量
TOKEN = environ.get("TELEGRAM_BOT_TOKEN")
PORT = int(environ.get("PORT", "10000"))
RENDER_URL = environ.get("RENDER_EXTERNAL_URL")
WEBHOOK_URL = f"{RENDER_URL}/{TOKEN}" if RENDER_URL else None
CREATOR_ID = environ.get("CREATOR_ID")

async def grant_creator_admin_privileges():
    """给创建者自动授予管理员权限"""
    if not CREATOR_ID:
        logger.info("未设置CREATOR_ID，跳过创建者权限授予")
        return
    
    try:
        creator_id = int(CREATOR_ID)
        # 确保用户存在于表中，如果不存在则插入
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
    """显示帮助和主菜单"""
    user_id = update.effective_user.id
    user_is_admin = await is_admin(user_id)
    
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
        text += "\n\n✨ 你拥有守护者权限，可使用管理功能。"
    
    keyboard = [
        [
            InlineKeyboardButton("🏆 英灵殿", callback_data="leaderboard_top_tagselect_1"),
            InlineKeyboardButton("☠️ 放逐深渊", callback_data="leaderboard_bottom_tagselect_1")
        ],
        [
            InlineKeyboardButton("🌟 我的星盘", callback_data="show_my_favorites"),
            InlineKeyboardButton("📊 神谕数据", callback_data="show_system_stats")
        ],
        [InlineKeyboardButton("🔥 抹除室", callback_data="erasure_menu")]
    ]
    
    if user_is_admin:
        keyboard.append([InlineKeyboardButton("🌌 时空枢纽", callback_data="admin_settings_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_content = {'text': text, 'reply_markup': reply_markup, 'parse_mode': 'Markdown'}
    
    if from_button or (update.callback_query and update.callback_query.data == 'back_to_help'):
        await update.callback_query.edit_message_text(**message_content)
    else:
        await update.message.reply_text(**message_content)

# ... (其他所有处理器函数保持不变) ...
# 我将省略粘贴所有处理器函数以保持简洁，它们不需要修改。
# 您只需要确保下面的启动逻辑被完全替换。
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await help_command(update, context)
async def all_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try: await query.answer()
    except (TimedOut, Exception): pass
    data = query.data
    user_id = update.effective_user.id
    try:
        if data.startswith("admin_"):
            if not await is_admin(user_id):
                await query.answer("❌ 权限不足", show_alert=True)
                return
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
            else: logger.warning(f"未处理的管理员回调: {data}")
        elif data.startswith("rep_"):
            if data.startswith("rep_detail_"): await show_reputation_details(update, context)
            elif data.startswith("rep_summary_"): await show_reputation_summary(update, context)
            elif data.startswith("rep_voters_menu_"): await show_voters_menu(update, context)
            elif data.startswith("rep_voters_"): await show_reputation_voters(update, context)
        elif data.startswith("leaderboard_"): await show_leaderboard(update, context)
        elif data == "show_my_favorites": await my_favorites(update, context)
        elif data.startswith("query_fav"): await handle_favorite_button(update, context)
        elif data == "show_system_stats": await show_system_stats(update, context)
        elif data.startswith("erasure_"): await handle_erasure_functions(update, context)
        elif data.startswith(("vote_", "tag_", "toggle_favorite_")):
            if data.startswith("vote_comment_"): await handle_vote_comment(update, context)
            elif data.startswith("vote_submit_"): await handle_vote_submit(update, context)
            else: await reputation_button_handler(update, context)
        elif data == "back_to_help": await help_command(update, context, from_button=True)
        elif data == "noop": pass
        else: logger.warning(f"未知的回调数据: {data}"); await query.answer("未知操作", show_alert=True)
    except Exception as e: logger.error(f"处理按钮回调时出错 {data}: {e}", exc_info=True)
async def execute_tag_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_id: int):
    query = update.callback_query
    try:
        tag_info = await db_fetch_one("SELECT name, type FROM tags WHERE id = $1", tag_id)
        if not tag_info: await query.edit_message_text("❌ 标签不存在或已被删除。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_tags")]])); return
        await db_execute("DELETE FROM tags WHERE id = $1", tag_id)
        type_name = "推荐" if tag_info['type'] == 'recommend' else "警告"
        message = f"✅ **{type_name}标签删除成功**\n\n标签 **{tag_info['name']}** 已被删除。"
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回标签管理", callback_data="admin_panel_tags")]]), parse_mode='Markdown')
    except Exception as e: logger.error(f"删除标签失败: {e}", exc_info=True)
async def execute_admin_removal(update: Update, context: ContextTypes.DEFAULT_TYPE, admin_id: int):
    query = update.callback_query
    try:
        admin_info = await db_fetch_one("SELECT username, first_name FROM users WHERE id = $1 AND is_admin = TRUE", admin_id)
        if not admin_info: await query.edit_message_text("❌ 用户不存在或不是管理员。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_permissions")]])); return
        await db_execute("UPDATE users SET is_admin = FALSE WHERE id = $1", admin_id)
        name = admin_info['first_name'] or admin_info['username'] or f"用户{admin_id}"
        message = f"✅ **管理员权限移除成功**\n\n用户 **{name}** 的管理员权限已被移除。"
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回权限管理", callback_data="admin_panel_permissions")]]), parse_mode='Markdown')
    except Exception as e: logger.error(f"移除管理员失败: {e}", exc_info=True)
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for key in ['next_action', 'comment_input', 'current_vote']: context.user_data.pop(key, None)
    await update.message.reply_text("✅ 操作已取消")
async def commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_admin(update.effective_user.id): await show_all_commands(update, context, from_command=True)
    else: await update.message.reply_text("❌ 此命令仅管理员可用")
async def private_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await handle_comment_input(update, context): return
    if await is_admin(update.effective_user.id): await process_admin_input(update, context)
    else: await update.message.reply_text("我不明白您的意思。")
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"异常由更新引发: {context.error}", exc_info=context.error)

# --- 关键修复点：移除 post_init，将其逻辑移入 lifespan ---
ptb_app = Application.builder().token(TOKEN).build()

# --- 统一的生命周期管理 (Lifespan) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 启动神谕者机器人...")
    # --- 步骤 1: 初始化数据库 ---
    await init_pool()
    logger.info("✅ 数据库连接池已创建")
    
    # --- 步骤 2: 创建数据表 ---
    await create_tables()
    logger.info("✅ 数据表结构已验证/创建")

    # --- 步骤 3: 授予创始人管理员权限 ---
    await grant_creator_admin_privileges()
    
    # --- 步骤 4: 启动 PTB 核心应用 ---
    async with ptb_app:
        await ptb_app.initialize() # 初始化应用
        await ptb_app.start()      # 开始后台任务
        
        # --- 步骤 5: 设置 Webhook ---
        await ptb_app.bot.delete_webhook(drop_pending_updates=True)
        if WEBHOOK_URL:
            await ptb_app.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES)
            logger.info(f"✅ Webhook已设置: {WEBHOOK_URL}")
        else:
            logger.warning("⚠️ 未设置RENDER_EXTERNAL_URL，webhook可能无法工作")
        
        logger.info("✅ 神谕者已就绪并开始监听")
        yield # FastAPI 服务在此运行
        
    # --- 关闭流程 ---
    logger.info("🔌 关闭神谕者机器人...")
    if ptb_app.running:
        await ptb_app.stop()
    await close_pool()
    logger.info("数据库连接池已关闭")

# --- 主函数和 FastAPI 应用设置 ---
def main():
    if not TOKEN: logger.critical("❌ TELEGRAM_BOT_TOKEN 环境变量未设置"); return
    
    fastapi_app = FastAPI(title="神谕者机器人", description="Telegram声誉管理机器人", version="2.0.1", lifespan=lifespan)
    
    # 添加处理器
    ptb_app.add_error_handler(error_handler)
    ptb_app.add_handler(CommandHandler(["start", "help"], start_command))
    ptb_app.add_handler(CommandHandler("godmode", god_mode_command))
    ptb_app.add_handler(CommandHandler("cancel", cancel_command))
    ptb_app.add_handler(CommandHandler("myfavorites", my_favorites))
    ptb_app.add_handler(CommandHandler("commands", commands_command))
    ptb_app.add_handler(CallbackQueryHandler(all_button_handler))
    ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, private_text_handler))
    ptb_app.add_handler(MessageHandler(filters.Regex(r'(?:@(\w{5,}))|(?:查询\s*@(\w{5,}))') & ~filters.COMMAND & filters.ChatType.GROUPS, handle_nomination))
    ptb_app.add_handler(MessageHandler(filters.Regex(r'^查询\s+@(\w{5,})$') & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_username_query))
    
    @fastapi_app.post(f"/{TOKEN}", include_in_schema=False)
    async def process_telegram_update(request: Request):
        try:
            update = Update.de_json(await request.json(), ptb_app.bot)
            await ptb_app.process_update(update)
            return Response(status_code=200)
        except Exception as e:
            logger.error(f"处理Webhook时出错: {e}", exc_info=True)
            return Response(status_code=500)
    
    uvicorn.run(fastapi_app, host="0.0.0.0", port=PORT, log_level="info")

if __name__ == "__main__":
    main()
