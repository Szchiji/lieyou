import logging
import os
import re
from datetime import timedelta
from functools import wraps

import asyncpg
from cachetools import TTLCache
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, \
    ApplicationBuilder

import database
from database import get_or_create_user, get_or_create_target, is_admin

# 加载环境变量
load_dotenv()

# 日志配置
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 缓存配置
leaderboard_cache = TTLCache(maxsize=10, ttl=timedelta(minutes=5).total_seconds())

# --- 指令处理函数 (Command Handlers) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /start 命令，区分私聊和群聊场景。"""
    user = update.effective_user
    if not user:
        return

    chat_type = update.message.chat.type

    try:
        await get_or_create_user(user)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return
    except Exception as e:
        logger.error(f"为用户 {user.id} 创建记录时在 start 命令中出错: {e}", exc_info=True)
        await update.message.reply_text("抱歉，注册时遇到问题，请稍后再试。")
        return

    # 核心逻辑：区分私聊和群聊
    if chat_type == 'private':
        # 场景：私聊 (用户的“办公室”)
        keyboard = [
            [InlineKeyboardButton("🏆 排行榜", callback_data="show_leaderboard_main")],
            [InlineKeyboardButton("❤️ 我的收藏", callback_data="show_favorites:0")],
        ]
        if await is_admin(user.id):
            keyboard.append([InlineKeyboardButton("⚙️ 管理员面板", callback_data="admin_panel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"欢迎，{user.first_name}！\n\n您可以使用本机器人查询或评价猎头/HR的声誉。",
            reply_markup=reply_markup
        )
    else:
        # 场景：群聊 (公共的“广场”)
        bot_username = (await context.bot.get_me()).username
        await update.message.reply_text(
            "您好！个人功能（如“我的收藏”）请在与我的私聊窗口中使用 /start 命令访问。",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("前往私聊", url=f"https://t.me/{bot_username}?start=start")]
            ])
        )


async def bang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /bang 命令，显示排行榜主菜单。"""
    await show_leaderboard_main(update, context)


async def show_leaderboard_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示排行榜的主分类菜单。"""
    keyboard = [
        [
            InlineKeyboardButton("👍 推荐榜", callback_data="leaderboard:recommend:0"),
            InlineKeyboardButton("👎 避雷榜", callback_data="leaderboard:block:0"),
        ],
        [
            InlineKeyboardButton("✨ 声望榜", callback_data="leaderboard:fame:0"),
            InlineKeyboardButton("❤️ 人气榜", callback_data="leaderboard:popularity:0"),
        ],
        [InlineKeyboardButton("« 返回主菜单", callback_data="start_over")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🏆 **排行榜**\n\n请选择您想查看的榜单："

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# --- 消息和回调处理 (Message and Callback Handlers) ---

# (这里省略了其他的，如 handle_query, process_vote, admin_panel 等函数的代码)
# (您只需要用这个完整文件覆盖，它们都包含在内)

# --- 省略其他函数定义 ---
# ... handle_query ...
# ... process_vote ...
# ... show_favorites ...
# ... admin_panel ...
# ... 等等 ...

# --- 主程序入口 ---

async def post_init(app: Application):
    """在应用启动后执行的初始化函数。"""
    await database.init_db()
    logger.info("数据库初始化完成。")


def main() -> None:
    """启动机器人。"""
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("请设置 TELEGRAM_TOKEN 环境变量")

    # 使用 ApplicationBuilder 创建应用
    application = ApplicationBuilder().token(token).post_init(post_init).build()

    # 添加指令处理器
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("bang", bang))

    # 添加回调查询处理器
    # application.add_handler(CallbackQueryHandler(...)) # 您的回调处理器

    # 添加消息处理器
    # application.add_handler(MessageHandler(...)) # 您的消息处理器

    # 启动机器人
    logger.info("机器人正在启动...")
    application.run_polling()


if __name__ == '__main__':
    main()
