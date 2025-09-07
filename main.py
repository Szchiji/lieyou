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
from database import get_or_create_user, get_or_create_target, is_admin, db_fetch_all, db_fetch_one, db_execute

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

# --- 权限装饰器 ---
def admin_required(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not await is_admin(user.id):
            await update.callback_query.answer("❌ 您没有权限执行此操作。", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

# --- 指令处理函数 ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /start 命令，区分私聊和群聊场景。"""
    user = update.effective_user
    if not user: return
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

    if chat_type == 'private':
        keyboard = [
            [InlineKeyboardButton("🏆 排行榜", callback_data="show_leaderboard_main")],
            [InlineKeyboardButton("❤️ 我的收藏", callback_data="show_favorites:0")],
        ]
        if await is_admin(user.id):
            keyboard.append([InlineKeyboardButton("⚙️ 管理员面板", callback_data="admin_panel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"欢迎，{user.first_name}！\n\n您可以使用本机器人查询或评价他人的声誉。",
            reply_markup=reply_markup
        )
    else:
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

# --- 核心评价流程 ---

async def handle_mention_evaluation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    处理群聊中 @某人 的消息，发起评价流程。
    这是新的、更优雅的评价入口。
    """
    user = update.effective_user
    message_text = update.message.text.strip()
    
    # 正则表达式确保消息只包含一个 @用户名
    match = re.fullmatch(r'@(\w+)', message_text)
    if not match:
        return

    target_username = match.group(1)
    
    try:
        # 验证发起者
        await get_or_create_user(user)
        # 为目标建档
        target_user = await get_or_create_target(target_username)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return
    except Exception as e:
        logger.error(f"处理 @{target_username} 评价时数据库出错: {e}", exc_info=True)
        await update.message.reply_text("❌ 数据库错误，请稍后再试。")
        return

    keyboard = [
        [
            InlineKeyboardButton("👍 推荐", callback_data=f"ask_tags:recommend:{target_user['pkid']}"),
            InlineKeyboardButton("👎 警告", callback_data=f"ask_tags:block:{target_user['pkid']}"),
        ],
        [InlineKeyboardButton("❌ 取消", callback_data="cancel_vote")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"您想如何评价 @{target_username}？",
        reply_markup=reply_markup
    )

async def ask_for_tags(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    在用户选择“推荐”或“警告”后，展示对应的标签供选择。
    """
    query = update.callback_query
    await query.answer()

    _, vote_type, target_pkid_str = query.data.split(':')
    target_pkid = int(target_pkid_str)
    
    # 权限检查：只有发起者才能点击按钮
    original_user_id = query.from_user.id
    message_user_id = query.message.reply_to_message.from_user.id
    if original_user_id != message_user_id:
        await query.answer("❌ 这不是您可以操作的菜单。", show_alert=True)
        return

    try:
        tags = await db_fetch_all("SELECT pkid, name FROM tags WHERE type = $1", vote_type)
        target_user = await db_fetch_one("SELECT username FROM users WHERE pkid = $1", target_pkid)

        if not tags:
            await query.edit_message_text(f"❌ 系统中还没有设置任何“{vote_type}”类型的标签。")
            return

        keyboard = []
        for tag in tags:
            keyboard.append([InlineKeyboardButton(tag['name'], callback_data=f"vote:{vote_type}:{tag['pkid']}:{target_pkid}")])
        
        keyboard.append([InlineKeyboardButton("« 返回", callback_data=f"back_to_type_select:{target_pkid}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        header_text = "👍 请为他选择推荐标签：" if vote_type == 'recommend' else "👎 请为他选择警告标签："
        await query.edit_message_text(f"@{target_user['username']}\n{header_text}", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"获取标签时出错: {e}", exc_info=True)
        await query.edit_message_text("❌ 获取标签列表时出错。")

async def process_vote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理最终的标签投票。"""
    query = update.callback_query
    await query.answer()

    _, vote_type, tag_pkid_str, target_pkid_str = query.data.split(':')
    tag_pkid = int(tag_pkid_str)
    target_pkid = int(target_pkid_str)
    
    # 权限检查
    original_user_id = query.from_user.id
    message_user_id = query.message.reply_to_message.from_user.id
    if original_user_id != message_user_id:
        await query.answer("❌ 这不是您可以操作的菜单。", show_alert=True)
        return

    try:
        user_record = await get_or_create_user(query.from_user)
        user_pkid = user_record['pkid']

        if user_pkid == target_pkid:
            await query.edit_message_text("❌ 您不能评价自己。")
            return

        await db_execute(
            """
            INSERT INTO evaluations (user_pkid, target_user_pkid, tag_pkid, type)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_pkid, target_user_pkid, tag_pkid) DO UPDATE SET type = EXCLUDED.type
            """,
            user_pkid, target_pkid, tag_pkid, vote_type
        )
        
        tag_name = await database.db_fetch_val("SELECT name FROM tags WHERE pkid = $1", tag_pkid)
        target_username = await database.db_fetch_val("SELECT username FROM users WHERE pkid = $1", target_pkid)

        vote_action_text = "推荐" if vote_type == "recommend" else "警告"
        await query.edit_message_text(f"✅ 您已成功将 @{target_username} 标记为 **{tag_name}** ({vote_action_text})。", parse_mode='Markdown')
        
        # 可选：在这里调用一个函数来更新公开的声誉卡片
        # await update_reputation_card(context, query.message.chat_id, target_pkid)

    except Exception as e:
        logger.error(f"处理投票时出错: {e}", exc_info=True)
        await query.edit_message_text("❌ 处理投票时发生数据库错误。")

async def cancel_vote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """取消评价操作。"""
    query = update.callback_query
    # 权限检查
    if query.from_user.id != query.message.reply_to_message.from_user.id:
        await query.answer("❌ 这不是您可以操作的菜单。", show_alert=True)
        return
    await query.edit_message_text("❌ 操作已取消。")

async def back_to_type_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """从标签选择返回到类型选择。"""
    query = update.callback_query
    await query.answer()

    _, target_pkid_str = query.data.split(':')
    target_pkid = int(target_pkid_str)

    # 权限检查
    if query.from_user.id != query.message.reply_to_message.from_user.id:
        await query.answer("❌ 这不是您可以操作的菜单。", show_alert=True)
        return
        
    target_username = await database.db_fetch_val("SELECT username FROM users WHERE pkid = $1", target_pkid)
    
    keyboard = [
        [
            InlineKeyboardButton("👍 推荐", callback_data=f"ask_tags:recommend:{target_pkid}"),
            InlineKeyboardButton("👎 警告", callback_data=f"ask_tags:block:{target_pkid}"),
        ],
        [InlineKeyboardButton("❌ 取消", callback_data="cancel_vote")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"您想如何评价 @{target_username}？",
        reply_markup=reply_markup
    )
    
# --- 其他功能占位 ---
# show_leaderboard_main, show_favorites, admin_panel 等函数需要在这里实现
# 由于代码过长，此处省略，但请确保您的文件中有这些函数的完整实现

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

    application = ApplicationBuilder().token(token).post_init(post_init).build()

    # 指令处理器
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("bang", bang))

    # 核心评价流程处理器
    # 修改：使用新的更精确的触发器
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r'^@(\w+)$'), handle_mention_evaluation))
    
    # 回调查询处理器
    application.add_handler(CallbackQueryHandler(ask_for_tags, pattern=r'^ask_tags:'))
    application.add_handler(CallbackQueryHandler(process_vote, pattern=r'^vote:'))
    application.add_handler(CallbackQueryHandler(cancel_vote, pattern=r'^cancel_vote$'))
    application.add_handler(CallbackQueryHandler(back_to_type_select, pattern=r'^back_to_type_select:'))
    
    # --- 其他处理器 ---
    # application.add_handler(CallbackQueryHandler(show_leaderboard_main, pattern=r'^show_leaderboard_main$'))
    # application.add_handler(CallbackQueryHandler(show_favorites, pattern=r'^show_favorites:'))
    # application.add_handler(CallbackQueryHandler(admin_panel, pattern=r'^admin_panel$'))
    # ... 您其他的回调处理器 ...

    logger.info("机器人正在启动...")
    application.run_polling()


if __name__ == '__main__':
    main()
