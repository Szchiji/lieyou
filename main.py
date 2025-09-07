import logging
import os
import re
from datetime import timedelta
from functools import wraps

from cachetools import TTLCache
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, \
    ApplicationBuilder

import database
from database import get_or_create_user, get_or_create_target, is_admin, db_fetch_all, db_fetch_one, db_execute

# --- 初始化 ---
load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 权限装饰器 ---
def admin_required(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not await is_admin(user.id):
            if update.callback_query:
                await update.callback_query.answer("❌ 您没有权限执行此操作。", show_alert=True)
            else:
                await update.message.reply_text("❌ 您没有权限执行此操作。")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

# --- 帮助与菜单更新 ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示帮助信息"""
    await update.message.reply_text("这是一个声誉评价机器人。\n\n- 在群聊中 @某人 即可发起评价。\n- 使用 /bang 或输入“排行榜”查看排名。\n- 使用底部的菜单按钮可以快速访问核心功能。")

async def update_bot_commands(app: Application):
    """从数据库读取并设置机器人的菜单按钮"""
    buttons = await db_fetch_all("SELECT command, description FROM menu_buttons WHERE is_enabled = TRUE ORDER BY sort_order")
    commands = [BotCommand(button['command'], button['description']) for button in buttons]
    await app.bot.set_my_commands(commands)
    logger.info(f"已从数据库更新了 {len(commands)} 个菜单按钮。")

# --- 指令处理函数 ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user: return
    chat_type = update.message.chat.type
    try: await get_or_create_user(user)
    except Exception as e:
        logger.error(f"为用户 {user.id} 创建记录时在 start 命令中出错: {e}", exc_info=True)
        await update.message.reply_text("抱歉，注册时遇到问题，请稍后再试或设置用户名。")
        return

    if chat_type == 'private':
        keyboard = [[InlineKeyboardButton("🏆 排行榜", callback_data="show_leaderboard_main")]]
        if await is_admin(user.id):
            keyboard.append([InlineKeyboardButton("⚙️ 管理员面板", callback_data="admin_panel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"欢迎，{user.first_name}！\n请使用下方的菜单按钮或直接输入指令。", reply_markup=reply_markup)
    else:
        await update.message.reply_text("机器人已在此群组激活。")

async def start_over(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 此函数用于从内联键盘返回主菜单，逻辑与start类似
    query = update.callback_query
    await query.answer()
    user = query.from_user
    keyboard = [[InlineKeyboardButton("🏆 排行榜", callback_data="show_leaderboard_main")]]
    if await is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ 管理员面板", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"欢迎，{user.first_name}！\n请使用下方的菜单按钮或直接输入指令。", reply_markup=reply_markup)

async def bang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_leaderboard_main(update, context)

# --- 核心评价流程 (代码不变，保持原样) ---
async def handle_mention_evaluation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... 此处省略评价流程的完整代码，与上一版完全相同 ...
    user = update.effective_user; message_text = update.message.text.strip(); match = re.fullmatch(r'@(\w+)', message_text)
    if not match: return
    target_username = match.group(1)
    try: await get_or_create_user(user); target_user = await get_or_create_target(target_username)
    except ValueError as e: await update.message.reply_text(str(e)); return
    except Exception as e: logger.error(f"处理 @{target_username} 评价时数据库出错: {e}", exc_info=True); await update.message.reply_text("❌ 数据库错误。"); return
    keyboard = [[InlineKeyboardButton("👍 推荐", callback_data=f"ask_tags:recommend:{target_user['pkid']}"), InlineKeyboardButton("👎 警告", callback_data=f"ask_tags:block:{target_user['pkid']}")], [InlineKeyboardButton("❌ 取消", callback_data="cancel_vote")]]; reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"您想如何评价 @{target_username}？", reply_markup=reply_markup)
async def ask_for_tags(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; await query.answer(); _, vote_type, target_pkid_str = query.data.split(':'); target_pkid = int(target_pkid_str)
    if query.from_user.id != query.message.reply_to_message.from_user.id: await query.answer("❌ 非本人操作", show_alert=True); return
    try:
        tags = await db_fetch_all("SELECT pkid, name FROM tags WHERE type = $1", vote_type); target_user = await db_fetch_one("SELECT username FROM users WHERE pkid = $1", target_pkid)
        if not tags: await query.edit_message_text(f"❌ 系统中还没有“{vote_type}”类型标签。"); return
        keyboard = [[InlineKeyboardButton(tag['name'], callback_data=f"vote:{vote_type}:{tag['pkid']}:{target_pkid}")] for tag in tags]; keyboard.append([InlineKeyboardButton("« 返回", callback_data=f"back_to_type_select:{target_pkid}")]); reply_markup = InlineKeyboardMarkup(keyboard)
        header_text = "👍 请选择推荐标签：" if vote_type == 'recommend' else "👎 请选择警告标签："; await query.edit_message_text(f"@{target_user['username']}\n{header_text}", reply_markup=reply_markup)
    except Exception as e: logger.error(f"获取标签时出错: {e}", exc_info=True); await query.edit_message_text("❌ 获取标签列表出错。")
async def process_vote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; await query.answer(); _, vote_type, tag_pkid_str, target_pkid_str = query.data.split(':'); tag_pkid, target_pkid = int(tag_pkid_str), int(target_pkid_str)
    if query.from_user.id != query.message.reply_to_message.from_user.id: await query.answer("❌ 非本人操作", show_alert=True); return
    try:
        user_pkid = (await get_or_create_user(query.from_user))['pkid']
        if user_pkid == target_pkid: await query.edit_message_text("❌ 您不能评价自己。"); return
        await db_execute("INSERT INTO evaluations (user_pkid, target_user_pkid, tag_pkid, type) VALUES ($1, $2, $3, $4) ON CONFLICT (user_pkid, target_user_pkid, tag_pkid) DO UPDATE SET type = EXCLUDED.type", user_pkid, target_pkid, tag_pkid, vote_type)
        tag_name = await database.db_fetch_val("SELECT name FROM tags WHERE pkid = $1", tag_pkid); target_username = await database.db_fetch_val("SELECT username FROM users WHERE pkid = $1", target_pkid)
        vote_action_text = "推荐" if vote_type == "recommend" else "警告"; await query.edit_message_text(f"✅ 您已成功将 @{target_username} 标记为 **{tag_name}** ({vote_action_text})。", parse_mode='Markdown')
    except Exception as e: logger.error(f"处理投票时出错: {e}", exc_info=True); await query.edit_message_text("❌ 处理投票时发生数据库错误。")
async def cancel_vote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query;
    if query.from_user.id != query.message.reply_to_message.from_user.id: await query.answer("❌ 非本人操作", show_alert=True); return
    await query.edit_message_text("❌ 操作已取消。")
async def back_to_type_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; await query.answer(); _, target_pkid_str = query.data.split(':'); target_pkid = int(target_pkid_str)
    if query.from_user.id != query.message.reply_to_message.from_user.id: await query.answer("❌ 非本人操作", show_alert=True); return
    target_username = await database.db_fetch_val("SELECT username FROM users WHERE pkid = $1", target_pkid)
    keyboard = [[InlineKeyboardButton("👍 推荐", callback_data=f"ask_tags:recommend:{target_pkid}"), InlineKeyboardButton("👎 警告", callback_data=f"ask_tags:block:{target_pkid}")], [InlineKeyboardButton("❌ 取消", callback_data="cancel_vote")]]; reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"您想如何评价 @{target_username}？", reply_markup=reply_markup)


# --- 排行榜、管理员面板 ---
async def show_leaderboard_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[InlineKeyboardButton("👍 推荐榜", callback_data="leaderboard:recommend:0"), InlineKeyboardButton("👎 避雷榜", callback_data="leaderboard:block:0")], [InlineKeyboardButton("« 返回主菜单", callback_data="start_over")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🏆 **排行榜**\n\n请选择您想查看的榜单："
    if update.callback_query: await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else: await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

@admin_required
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🔧 管理菜单按钮", callback_data="admin_menu_buttons")],
        [InlineKeyboardButton("✏️ 管理标签", callback_data="admin_tags")], # 占位
        [InlineKeyboardButton("« 返回主菜单", callback_data="start_over")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("⚙️ **管理员面板**", reply_markup=reply_markup, parse_mode='Markdown')

@admin_required
async def admin_manage_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示菜单按钮管理界面"""
    query = update.callback_query
    await query.answer()
    buttons = await db_fetch_all("SELECT id, command, description, is_enabled FROM menu_buttons ORDER BY sort_order")
    
    keyboard = []
    for btn in buttons:
        status_icon = "✅" if btn['is_enabled'] else "❌"
        keyboard.append([
            InlineKeyboardButton(f"{status_icon} /{btn['command']} - {btn['description']}", callback_data=f"admin_toggle_menu:{btn['id']}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔄 刷新菜单", callback_data="admin_refresh_menu")])
    keyboard.append([InlineKeyboardButton("« 返回管理面板", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("🔧 **管理底部菜单按钮**\n点击按钮可以切换其启用/禁用状态。", reply_markup=reply_markup)

@admin_required
async def admin_toggle_menu_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """切换菜单按钮的启用状态"""
    query = update.callback_query
    _, button_id_str = query.data.split(':')
    button_id = int(button_id_str)
    
    current_status = await database.db_fetch_val("SELECT is_enabled FROM menu_buttons WHERE id = $1", button_id)
    await db_execute("UPDATE menu_buttons SET is_enabled = $1 WHERE id = $2", not current_status, button_id)
    
    # 重新加载管理界面
    await admin_manage_menu(update, context)

@admin_required
async def admin_refresh_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """手动刷新机器人的菜单命令"""
    query = update.callback_query
    await query.answer("正在刷新机器人菜单命令...")
    await update_bot_commands(context.application)
    await query.answer("✅ 菜单已刷新！请重启您的Telegram客户端查看更新。")
    # 重新加载管理界面
    await admin_manage_menu(update, context)


# --- 主程序入口 ---
async def post_init(app: Application):
    """在应用启动后执行的初始化函数"""
    await database.init_db()
    logger.info("数据库初始化完成。")
    await update_bot_commands(app)

def main() -> None:
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token: raise ValueError("请设置 TELEGRAM_TOKEN 环境变量")

    application = ApplicationBuilder().token(token).post_init(post_init).build()

    # 指令处理器
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("bang", bang))
    application.add_handler(CommandHandler("help", help_command))

    # 新增：自然语言处理器
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r'^排行榜$'), show_leaderboard_main))
    
    # 核心评价流程处理器
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r'^@(\w+)$'), handle_mention_evaluation))
    
    # 回调查询处理器
    application.add_handler(CallbackQueryHandler(start_over, pattern=r'^start_over$'))
    application.add_handler(CallbackQueryHandler(show_leaderboard_main, pattern=r'^show_leaderboard_main$'))
    # 评价
    application.add_handler(CallbackQueryHandler(ask_for_tags, pattern=r'^ask_tags:'))
    application.add_handler(CallbackQueryHandler(process_vote, pattern=r'^vote:'))
    application.add_handler(CallbackQueryHandler(cancel_vote, pattern=r'^cancel_vote$'))
    application.add_handler(CallbackQueryHandler(back_to_type_select, pattern=r'^back_to_type_select:'))
    # 管理员
    application.add_handler(CallbackQueryHandler(admin_panel, pattern=r'^admin_panel$'))
    application.add_handler(CallbackQueryHandler(admin_manage_menu, pattern=r'^admin_menu_buttons$'))
    application.add_handler(CallbackQueryHandler(admin_toggle_menu_status, pattern=r'^admin_toggle_menu:'))
    application.add_handler(CallbackQueryHandler(admin_refresh_menu, pattern=r'^admin_refresh_menu$'))

    logger.info("机器人正在启动...")
    application.run_polling(drop_pending_updates=True) # 增加此参数防止冲突

if __name__ == '__main__':
    main()
