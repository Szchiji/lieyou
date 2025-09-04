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
from database import init_pool, create_tables, is_admin, get_setting, db_execute, db_fetch_one

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
    mottos_panel,
    permissions_panel, 
    system_settings_panel, 
    leaderboard_panel,
    add_tag_prompt, 
    remove_tag_menu, 
    remove_tag_confirm, 
    list_all_tags,
    add_motto_prompt,
    list_mottos,
    remove_motto_menu,
    confirm_motto_deletion,
    execute_motto_deletion,
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

async def grant_creator_admin_privileges(app: Application):
    """给创建者自动授予管理员权限"""
    if not CREATOR_ID:
        logger.info("未设置CREATOR_ID，跳过创建者权限授予")
        return
    
    try:
        creator_id = int(CREATOR_ID)
        await db_execute(
            "INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE",
            creator_id
        )
        logger.info(f"✅ 创建者 {creator_id} 已获得管理员权限")
    except ValueError:
        logger.error("CREATOR_ID 必须是数字")
    except Exception as e:
        logger.error(f"❌ 授予创建者管理员权限失败: {e}", exc_info=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button: bool = False):
    """显示帮助和主菜单"""
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
        text += "\n\n✨ 你拥有守护者权限，可使用管理功能。"
    
    # 构建主菜单按钮
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
    
    # 管理员专属按钮
    if user_is_admin:
        keyboard.append([InlineKeyboardButton("🌌 时空枢纽", callback_data="admin_settings_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_content = {
        'text': text, 
        'reply_markup': reply_markup, 
        'parse_mode': 'Markdown'
    }
    
    # 判断是否通过按钮触发
    if from_button or (update.callback_query and update.callback_query.data == 'back_to_help'):
        await update.callback_query.edit_message_text(**message_content)
    else:
        await update.message.reply_text(**message_content)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理/start命令"""
    await help_command(update, context)

async def all_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """统一的按钮回调处理器"""
    query = update.callback_query
    
    # 尝试应答查询，防止超时
    try:
        await query.answer()
    except TimedOut:
        logger.warning(f"查询 {query.id} 响应超时")
    except Exception as e:
        logger.error(f"响应查询时出错: {e}")
    
    data = query.data
    user_id = update.effective_user.id
    
    try:
        # === 管理员功能 ===
        if data.startswith("admin_"):
            if not await is_admin(user_id):
                await query.answer("❌ 权限不足", show_alert=True)
                return
            
            if data == "admin_settings_menu":
                await settings_menu(update, context)
            
            # 标签管理
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
            elif data.startswith("admin_tag_delete_"):
                tag_id = int(data.split("_")[-1])
                await execute_tag_deletion(update, context, tag_id)
            elif data == "admin_tags_list":
                await list_all_tags(update, context)
            
            # 箴言便签管理
            elif data == "admin_panel_mottos":
                await mottos_panel(update, context)
            elif data == "admin_add_motto_prompt":
                await add_motto_prompt(update, context)
            elif data == "admin_list_mottos":
                await list_mottos(update, context)
            elif data.startswith("admin_remove_motto_menu_"):
                page = int(data.split("_")[-1])
                await remove_motto_menu(update, context, page)
            elif data.startswith("admin_motto_delete_confirm_"):
                parts = data.split("_")
                motto_id = int(parts[-2])
                page = int(parts[-1])
                await confirm_motto_deletion(update, context, motto_id, page)
            elif data.startswith("admin_motto_delete_"):
                motto_id = int(data.split("_")[-1])
                await execute_motto_deletion(update, context, motto_id)
            
            # 权限管理
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
            elif data.startswith("admin_remove_admin_"):
                admin_id = int(data.split("_")[-1])
                await execute_admin_removal(update, context, admin_id)
            
            # 系统设置
            elif data == "admin_panel_system":
                await system_settings_panel(update, context)
            elif data == "admin_system_set_start_message":
                await set_start_message_prompt(update, context)
            elif data.startswith("admin_system_set_prompt_"):
                key = data.replace("admin_system_set_prompt_", "")
                await set_setting_prompt(update, context, key)
            
            # 排行榜管理
            elif data == "admin_leaderboard_panel":
                await leaderboard_panel(update, context)
            elif data == "admin_leaderboard_remove_prompt":
                await remove_from_leaderboard_prompt(update, context)
            elif data == "admin_leaderboard_clear_cache":
                clear_leaderboard_cache()
                await query.answer("✅ 排行榜缓存已清除", show_alert=True)
            
            # 选择性抹除用户
            elif data == "admin_selective_remove_menu":
                await selective_remove_menu(update, context, "top", 1)
            elif data.startswith("admin_selective_remove_"):
                parts = data.split("_")
                board_type = parts[3]
                page = int(parts[4])
                await selective_remove_menu(update, context, board_type, page)
            elif data.startswith("admin_confirm_remove_user_"):
                parts = data.split("_")
                user_id_to_remove = int(parts[4])
                board_type = parts[5]
                page = int(parts[6])
                await confirm_user_removal(update, context, user_id_to_remove, board_type, page)
            elif data.startswith("admin_remove_user_"):
                parts = data.split("_")
                removal_type = parts[3]  # received 或 all
                user_id_to_remove = int(parts[4])
                board_type = parts[5]
                page = int(parts[6])
                await execute_user_removal(update, context, user_id_to_remove, removal_type, board_type, page)
            
            # 命令帮助
            elif data == "admin_show_commands":
                await show_all_commands(update, context)
            
            else:
                logger.warning(f"未处理的管理员回调: {data}")
        
        # === 声誉相关功能 ===
        elif data.startswith("rep_"):
            if data.startswith("rep_detail_"):
                await show_reputation_details(update, context)
            elif data.startswith("rep_summary_"):
                await show_reputation_summary(update, context)
            elif data.startswith("rep_voters_menu_"):
                await show_voters_menu(update, context)
            elif data.startswith("rep_voters_"):
                await show_reputation_voters(update, context)
        
        # === 排行榜功能 ===
        elif data.startswith("leaderboard_"):
            await show_leaderboard(update, context)
        
        # === 收藏功能 ===
        elif data == "show_my_favorites":
            await my_favorites(update, context)
        elif data.startswith("query_fav"):
            await handle_favorite_button(update, context)
        
        # === 统计功能 ===
        elif data == "show_system_stats":
            await show_system_stats(update, context)
        
        # === 抹除室功能 ===
        elif data.startswith("erasure_"):
            await handle_erasure_functions(update, context)
        
        # === 投票和标签功能 ===
        elif data.startswith(("vote_", "tag_", "toggle_favorite_")):
            if data.startswith("vote_comment_"):
                await handle_vote_comment(update, context)
            elif data.startswith("vote_submit_"):
                await handle_vote_submit(update, context)
            else:
                await reputation_button_handler(update, context)
        
        # === 导航功能 ===
        elif data == "back_to_help":
            await help_command(update, context, from_button=True)
        
        # === 空操作 ===
        elif data == "noop":
            pass
        
        else:
            logger.warning(f"未知的回调数据: {data}")
            await query.answer("未知操作", show_alert=True)
    
    except Exception as e:
        logger.error(f"处理按钮回调时出错 {data}: {e}", exc_info=True)
        try:
            await query.answer("处理请求时出错，请稍后再试", show_alert=True)
        except:
            pass

async def execute_tag_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_id: int):
    """执行标签删除"""
    query = update.callback_query
    
    try:
        # 获取标签信息
        tag_info = await db_fetch_one("SELECT name, type FROM tags WHERE id = $1", tag_id)
        
        if not tag_info:
            await query.edit_message_text(
                "❌ 标签不存在或已被删除。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 返回", callback_data="admin_panel_tags")
                ]]),
                parse_mode='Markdown'
            )
            return
        
        # 删除标签
        await db_execute("DELETE FROM tags WHERE id = $1", tag_id)
        
        type_name = "推荐" if tag_info['type'] == 'recommend' else "警告"
        message = f"✅ **{type_name}标签删除成功**\n\n标签 **{tag_info['name']}** 已被删除。"
        
        keyboard = [[InlineKeyboardButton("🔙 返回标签管理", callback_data="admin_panel_tags")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        logger.info(f"管理员 {update.effective_user.id} 删除了标签 {tag_info['name']} (ID: {tag_id})")
        
    except Exception as e:
        logger.error(f"删除标签失败: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ 删除标签失败，请重试。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回", callback_data="admin_panel_tags")
            ]]),
            parse_mode='Markdown'
        )

async def execute_admin_removal(update: Update, context: ContextTypes.DEFAULT_TYPE, admin_id: int):
    """执行管理员移除"""
    query = update.callback_query
    
    try:
        # 获取管理员信息
        admin_info = await db_fetch_one(
            "SELECT username, first_name FROM users WHERE id = $1 AND is_admin = TRUE",
            admin_id
        )
        
        if not admin_info:
            await query.edit_message_text(
                "❌ 用户不存在或不是管理员。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 返回", callback_data="admin_panel_permissions")
                ]]),
                parse_mode='Markdown'
            )
            return
        
        # 移除管理员权限
        await db_execute("UPDATE users SET is_admin = FALSE WHERE id = $1", admin_id)
        
        name = admin_info['first_name'] or admin_info['username'] or f"用户{admin_id}"
        message = f"✅ **管理员权限移除成功**\n\n用户 **{name}** 的管理员权限已被移除。"
        
        keyboard = [[InlineKeyboardButton("🔙 返回权限管理", callback_data="admin_panel_permissions")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        logger.info(f"管理员 {update.effective_user.id} 移除了用户 {admin_id} 的管理员权限")
        
    except Exception as e:
        logger.error(f"移除管理员失败: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ 移除管理员失败，请重试。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回", callback_data="admin_panel_permissions")
            ]]),
            parse_mode='Markdown'
        )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消当前操作"""
    if 'next_action' in context.user_data:
        del context.user_data['next_action']
    if 'comment_input' in context.user_data:
        del context.user_data['comment_input']
    if 'current_vote' in context.user_data:
        del context.user_data['current_vote']
    await update.message.reply_text("✅ 操作已取消")

async def commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示所有命令（仅管理员）"""
    user_id = update.effective_user.id
    if await is_admin(user_id):
        await show_all_commands(update, context, from_command=True)
    else:
        await update.message.reply_text("❌ 此命令仅管理员可用")

async def private_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理私聊文本消息"""
    # 首先检查是否是评论输入
    if await handle_comment_input(update, context):
        return
    
    # 然后检查是否是管理员输入
    await process_admin_input(update, context)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理错误"""
    logger.error(f"异常由更新引发: {context.error}", exc_info=context.error)

# 创建应用
ptb_app = Application.builder().token(TOKEN).post_init(grant_creator_admin_privileges).build()

# 添加错误处理器
ptb_app.add_error_handler(error_handler)

# 添加命令处理器
ptb_app.add_handler(CommandHandler("godmode", god_mode_command))
ptb_app.add_handler(CommandHandler(["start", "help"], start_command))
ptb_app.add_handler(CommandHandler("cancel", cancel_command))
ptb_app.add_handler(CommandHandler("myfavorites", my_favorites))
ptb_app.add_handler(CommandHandler("commands", commands_command))

# 添加回调查询处理器
ptb_app.add_handler(CallbackQueryHandler(all_button_handler))

# 添加私聊文本处理器（包括管理员输入和评论输入）
ptb_app.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
    private_text_handler
))

# 添加群聊中的@用户处理
ptb_app.add_handler(MessageHandler(
    filters.Regex(r'(?:@(\w{5,}))|(?:查询\s*@(\w{5,}))') & ~filters.COMMAND & filters.ChatType.GROUPS,
    handle_nomination
))

# 添加私聊中的查询处理
ptb_app.add_handler(MessageHandler(
    filters.Regex(r'^查询\s+@(\w{5,})$') & ~filters.COMMAND & filters.ChatType.PRIVATE,
    handle_username_query
))

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI生命周期管理"""
    logger.info("🚀 启动神谕者机器人...")
    
    try:
        # 初始化数据库
        await init_pool()
        await create_tables()
        
        # 设置webhook
        await ptb_app.bot.delete_webhook(drop_pending_updates=True)
        if WEBHOOK_URL:
            await ptb_app.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES)
            logger.info(f"✅ Webhook已设置: {WEBHOOK_URL}")
        else:
            logger.warning("⚠️ 未设置RENDER_EXTERNAL_URL，webhook可能无法工作")
        
        # 启动应用
        async with ptb_app:
            await ptb_app.start()
            logger.info("✅ 神谕者已就绪并开始监听")
            yield
            
    except Exception as e:
        logger.critical(f"❌ 启动失败: {e}", exc_info=True)
        raise
    finally:
        logger.info("🔌 关闭神谕者机器人...")
        try:
            await ptb_app.stop()
        except Exception as e:
            logger.error(f"关闭应用时出错: {e}")

def main():
    """主函数"""
    # 检查必要的环境变量
    if not TOKEN:
        logger.critical("❌ TELEGRAM_BOT_TOKEN 环境变量未设置")
        return
    
    if not RENDER_URL:
        logger.warning("⚠️ RENDER_EXTERNAL_URL 未设置，这可能影响webhook功能")
    
    # 创建FastAPI应用
    fastapi_app = FastAPI(
        title="神谕者机器人",
        description="Telegram声誉管理机器人",
        version="2.0.0",
        lifespan=lifespan
    )
    
    @fastapi_app.get("/", include_in_schema=False)
    async def health_check():
        """健康检查端点"""
        return {
            "status": "ok", 
            "message": "神谕者正在运行",
            "bot_username": ptb_app.bot.username if ptb_app.bot else None
        }
    
    @fastapi_app.get("/health", include_in_schema=False)
    async def detailed_health():
        """详细健康检查"""
        try:
            bot_info = await ptb_app.bot.get_me() if ptb_app.bot else None
            return {
                "status": "healthy",
                "bot_info": {
                    "id": bot_info.id if bot_info else None,
                    "username": bot_info.username if bot_info else None,
                    "first_name": bot_info.first_name if bot_info else None
                },
                "webhook_url": WEBHOOK_URL
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
    
    @fastapi_app.post(f"/{TOKEN}", include_in_schema=False)
    async def process_telegram_update(request: Request):
        """处理Telegram webhook更新"""
        try:
            # 解析JSON数据
            json_data = await request.json()
            
            # 创建Update对象
            update = Update.de_json(json_data, ptb_app.bot)
            
            if update:
                # 处理更新
                await ptb_app.process_update(update)
                return Response(status_code=200)
            else:
                logger.warning("收到无效的更新数据")
                return Response(status_code=400)
                
        except Exception as e:
            logger.error(f"处理Webhook时出错: {e}", exc_info=True)
            return Response(status_code=500)
    
    # 启动服务器
    logger.info(f"🌐 启动FastAPI服务器，端口: {PORT}")
    try:
        uvicorn.run(
            fastapi_app, 
            host="0.0.0.0", 
            port=PORT,
            log_level="info"
        )
    except Exception as e:
        logger.critical(f"启动服务器失败: {e}", exc_info=True)

if __name__ == "__main__":
    main()
