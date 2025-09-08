import asyncio
import logging
import os
from dotenv import load_dotenv
from telegram import Update, MessageEntity
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

from bot_handlers.start import start
from bot_handlers.menu import private_menu_callback_handler, show_private_main_menu
from bot_handlers.reputation import (
    handle_any_mention, reputation_callback_handler, tag_callback_handler
)
from bot_handlers.leaderboard import show_leaderboard, leaderboard_callback_handler
from bot_handlers.report import generate_my_report
from bot_handlers.favorites import favorites_callback_handler
from bot_handlers.admin import admin_panel, build_admin_conversations
from bot_handlers.monitoring import run_suspicion_monitor

from database import init_db, close_db, save_user, promote_virtual_user

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("bot")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Unhandled exception: {context.error}", exc_info=context.error)
    try:
        if update and update.effective_message:
            await update.effective_message.chat.send_message("❌ 出错了，请稍后再试。")
    except Exception as e:
        logger.error(f"Send error message fail: {e}")

async def post_init(app: Application):
    await init_db()
    asyncio.create_task(run_suspicion_monitor(app.bot))
    logger.info("Bot initialized (webhook mode)")

async def post_shutdown(app: Application):
    await close_db()
    logger.info("Bot shutdown complete")

async def myreport_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await generate_my_report(update, context)

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_panel(update, context)

async def leaderboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_leaderboard(update, context)

async def query_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("用法：/query @用户名")
        return
    username = context.args[0].lstrip('@')
    fake_text = f"@{username}"
    update.message.text = fake_text
    update.message.entities = [MessageEntity(type=MessageEntity.MENTION, offset=0, length=len(fake_text))]
    await handle_any_mention(update, context)

async def fallback_text_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_private_main_menu(update, context)

async def track_user_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user and update.effective_user.id > 0:
        await save_user(update.effective_user)
        try:
            await promote_virtual_user(update.effective_user)
        except Exception as e:
            logger.debug(f"promote_virtual_user skip: {e}")

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN missing")

    # Webhook 配置
    # Render Web Service 会注入 PORT 和 RENDER_EXTERNAL_URL（也可自定义 WEBHOOK_BASE_URL）
    port = int(os.getenv("PORT", "10000"))
    base_url = os.getenv("WEBHOOK_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if not base_url:
        raise RuntimeError("WEBHOOK_BASE_URL or RENDER_EXTERNAL_URL is required for webhook deployment")
    # 确保 base_url 末尾无斜杠
    if base_url.endswith('/'):
        base_url = base_url[:-1]
    # 路径可自定义（建议随机路径），默认使用 /webhook/<前8位token>
    default_path = f"/webhook/{token[:8]}"
    url_path = os.getenv("WEBHOOK_PATH", default_path)
    if not url_path.startswith('/'):
        url_path = '/' + url_path
    webhook_url = f"{base_url}{url_path}"
    secret_token = os.getenv("SECRET_TOKEN", "")

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # 全局错误
    app.add_error_handler(error_handler)

    # 用户追踪
    app.add_handler(MessageHandler(filters.ALL, track_user_activity), group=0)

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myreport", myreport_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    app.add_handler(CommandHandler("query", query_cmd))

    # 私聊菜单文本（非命令非 mention）
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE &
        filters.TEXT &
        ~filters.COMMAND &
        ~filters.Entity(MessageEntity.MENTION),
        private_menu_callback_handler
    ))

    # 任意 @mention / text_mention
    app.add_handler(MessageHandler(
        (filters.Entity(MessageEntity.MENTION) | filters.Entity(MessageEntity.TEXT_MENTION)) &
        (filters.ChatType.GROUPS | filters.ChatType.PRIVATE),
        handle_any_mention
    ))

    # 收藏回调
    app.add_handler(CallbackQueryHandler(favorites_callback_handler, pattern="^(favview_|favdel_)"))
    # 声誉回调
    app.add_handler(CallbackQueryHandler(reputation_callback_handler, pattern="^rep_"))
    # 多标签回调
    app.add_handler(CallbackQueryHandler(tag_callback_handler, pattern="^(tagtoggle_|tagconfirm_|tagclear_|back_to_user_)"))
    # 排行榜分页回调
    app.add_handler(CallbackQueryHandler(leaderboard_callback_handler, pattern="^lb_page_"))

    # 管理对话
    admin_conv = build_admin_conversations()
    app.add_handler(admin_conv)

    logger.info(f"Starting webhook server on 0.0.0.0:{port} path={url_path} url={webhook_url}")
    # 运行 Webhook（会自动调用 setWebhook）
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=url_path.lstrip('/'),
        webhook_url=webhook_url,
        secret_token=secret_token or None,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )

if __name__ == "__main__":
    main()
