import logging
import os
import re
from functools import wraps
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, \
    ApplicationBuilder

import database
from database import get_or_create_user, get_or_create_target, is_admin, db_fetch_all, db_fetch_one, db_execute, db_fetch_val, is_favorited

# --- 初始化 ---
load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 伪装网站，用于应付 Render 的端口检查 ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is running")

def run_health_check_server():
    # Render 会自动注入 PORT 环境变量，通常是 10000
    port = int(os.environ.get("PORT", 10000))
    server_address = ('', port)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    logger.info(f"正在端口 {port} 上启动健康检查服务器...")
    httpd.serve_forever()

# --- 权限装饰器 (完整) ---
def admin_required(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user or not await is_admin(user.id):
            if update.callback_query: await update.callback_query.answer("❌ 您没有权限执行此操作。", show_alert=True)
            elif update.message: await update.message.reply_text("❌ 您没有权限执行此操作。")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

# --- 核心键盘与帮助 (完整) ---
async def get_main_keyboard() -> ReplyKeyboardMarkup:
    buttons_data = await db_fetch_all("SELECT text FROM menu_buttons WHERE is_enabled = TRUE ORDER BY sort_order")
    keyboard_layout = [buttons_data[i:i + 2] for i in range(0, len(buttons_data), 2)]
    keyboard = [[item['text'] for item in row] for row in keyboard_layout]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reply_markup = await get_main_keyboard()
    await update.message.reply_text("这是一个声誉评价机器人。\n\n- 在群聊中 @某人 即可发起评价。\n- 使用底部的键盘按钮可以快速访问核心功能。", reply_markup=reply_markup)

# --- 指令与按钮处理器 (完整) ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user: return
    try: await get_or_create_user(user)
    except Exception as e:
        logger.error(f"为用户 {user.id} 创建记录时出错: {e}", exc_info=True)
        await update.message.reply_text("抱歉，注册时遇到问题，请稍后再试或为您的TG账号设置用户名。")
        return
    reply_markup = await get_main_keyboard()
    await update.message.reply_text(f"欢迎，{user.first_name}！\n请使用下方的键盘按钮进行操作。", reply_markup=reply_markup)

async def show_private_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.chat.type != 'private':
        await update.message.reply_text("此功能仅限私聊使用。")
        return
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("🏆 排行榜", callback_data="show_leaderboard_main")],
        [InlineKeyboardButton("❤️ 我的收藏", callback_data="show_favorites:0")]
    ]
    if await is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ 管理员面板", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "请选择要执行的操作："
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else: await update.message.reply_text(text, reply_markup=reply_markup)

async def show_leaderboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[InlineKeyboardButton("👍 推荐榜", callback_data="leaderboard:recommend:0"), InlineKeyboardButton("👎 避雷榜", callback_data="leaderboard:block:0")]]
    if (update.message and update.message.chat.type == 'private') or update.callback_query:
         keyboard.append([InlineKeyboardButton("« 返回主菜单", callback_data="show_private_main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🏆 **排行榜**\n\n请选择您想查看的榜单："
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else: await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# --- 收藏夹功能 (完整实现) ---
async def show_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); user_record = await get_or_create_user(query.from_user); user_pkid = user_record['pkid']
    _, page_str = query.data.split(':'); page = int(page_str); limit = 5; offset = page * limit
    favorites = await db_fetch_all("""SELECT u.pkid, u.username FROM favorites f JOIN users u ON f.target_user_pkid = u.pkid WHERE f.user_pkid = $1 ORDER BY f.created_at DESC LIMIT $2 OFFSET $3""", user_pkid, limit, offset)
    total_count = await db_fetch_val("SELECT COUNT(*) FROM favorites WHERE user_pkid = $1", user_pkid)
    if not favorites and page == 0:
        await query.edit_message_text("您的收藏夹是空的。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« 返回主菜单", callback_data="show_private_main_menu")]])); return
    keyboard = []
    for fav in favorites: keyboard.append([InlineKeyboardButton(f"@{fav['username']}", callback_data=f"noop"), InlineKeyboardButton("❌ 移除", callback_data=f"remove_favorite:{fav['pkid']}:{page}")])
    nav_row = [];
    if page > 0: nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"show_favorites:{page-1}"))
    if (page + 1) * limit < total_count: nav_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"show_favorites:{page+1}"))
    if nav_row: keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton("« 返回主菜单", callback_data="show_private_main_menu")]); reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"❤️ **我的收藏** (第 {page+1} 页)", reply_markup=reply_markup, parse_mode='Markdown')

async def toggle_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); _, target_pkid_str = query.data.split(':'); target_pkid = int(target_pkid_str); user_record = await get_or_create_user(query.from_user); user_pkid = user_record['pkid']
    is_fav = await is_favorited(user_pkid, target_pkid); target_username = await db_fetch_val("SELECT username FROM users WHERE pkid = $1", target_pkid)
    if is_fav: await db_execute("DELETE FROM favorites WHERE user_pkid = $1 AND target_user_pkid = $2", user_pkid, target_pkid); await query.answer(f"已将 @{target_username} 移出收藏。")
    else: await db_execute("INSERT INTO favorites (user_pkid, target_user_pkid) VALUES ($1, $2) ON CONFLICT DO NOTHING", user_pkid, target_pkid); await query.answer(f"已将 @{target_username} 加入收藏！")
    is_fav_after = not is_fav; fav_button_text = "💔 取消收藏" if is_fav_after else "❤️ 添加收藏"; new_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(fav_button_text, callback_data=f"toggle_favorite:{target_pkid}")]])
    await query.edit_message_reply_markup(reply_markup=new_keyboard)

async def remove_favorite_from_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); _, target_pkid_str, page_str = query.data.split(':'); target_pkid = int(target_pkid_str); user_record = await get_or_create_user(query.from_user); user_pkid = user_record['pkid']
    await db_execute("DELETE FROM favorites WHERE user_pkid = $1 AND target_user_pkid = $2", user_pkid, target_pkid)
    query.data = f"show_favorites:{page_str}"; await show_favorites(update, context)

# --- 核心评价流程 (完整) ---
async def process_vote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; await query.answer(); _, vote_type, tag_pkid_str, target_pkid_str = query.data.split(':'); tag_pkid, target_pkid = int(tag_pkid_str), int(target_pkid_str)
    if query.from_user.id != query.message.reply_to_message.from_user.id: await query.answer("❌ 非本人操作", show_alert=True); return
    try:
        user_pkid = (await get_or_create_user(query.from_user))['pkid']
        if user_pkid == target_pkid: await query.edit_message_text("❌ 您不能评价自己。"); return
        await db_execute("INSERT INTO evaluations (user_pkid, target_user_pkid, tag_pkid, type) VALUES ($1, $2, $3, $4) ON CONFLICT (user_pkid, target_user_pkid, tag_pkid) DO UPDATE SET type = EXCLUDED.type", user_pkid, target_pkid, tag_pkid, vote_type)
        tag_name = await db_fetch_val("SELECT name FROM tags WHERE pkid = $1", tag_pkid); target_username = await db_fetch_val("SELECT username FROM users WHERE pkid = $1", target_pkid); vote_action_text = "推荐" if vote_type == "recommend" else "警告"
        is_fav = await is_favorited(user_pkid, target_pkid); fav_button_text = "💔 取消收藏" if is_fav else "❤️ 添加收藏"; reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(fav_button_text, callback_data=f"toggle_favorite:{target_pkid}")]])
        await query.edit_message_text(f"✅ 您已成功将 @{target_username} 标记为 **{tag_name}** ({vote_action_text})。", reply_markup=reply_markup, parse_mode='Markdown')
    except Exception as e: logger.error(f"处理投票时出错: {e}", exc_info=True); await query.edit_message_text("❌ 处理投票时发生数据库错误。")

# ... 其他函数保持完整 ...
async def handle_mention_evaluation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user; message_text = update.message.text.strip(); match = re.fullmatch(r'@(\w+)', message_text);
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
        tags = await db_fetch_all("SELECT pkid, name FROM tags WHERE type = $1 ORDER BY name", vote_type); target_user = await db_fetch_one("SELECT username FROM users WHERE pkid = $1", target_pkid)
        if not tags: await query.edit_message_text(f"❌ 系统中还没有“{vote_type}”类型标签。"); return
        keyboard = [[InlineKeyboardButton(tag['name'], callback_data=f"vote:{vote_type}:{tag['pkid']}:{target_pkid}")] for tag in tags]; keyboard.append([InlineKeyboardButton("« 返回", callback_data=f"back_to_type_select:{target_pkid}")]); reply_markup = InlineKeyboardMarkup(keyboard)
        header_text = "👍 请选择推荐标签：" if vote_type == 'recommend' else "👎 请选择警告标签："; await query.edit_message_text(f"@{target_user['username']}\n{header_text}", reply_markup=reply_markup)
    except Exception as e: logger.error(f"获取标签时出错: {e}", exc_info=True); await query.edit_message_text("❌ 获取标签列表出错。")
async def cancel_vote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query;
    if query.from_user.id != query.message.reply_to_message.from_user.id: await query.answer("❌ 非本人操作", show_alert=True); return
    await query.edit_message_text("❌ 操作已取消。")
async def back_to_type_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; await query.answer(); _, target_pkid_str = query.data.split(':'); target_pkid = int(target_pkid_str)
    if query.from_user.id != query.message.reply_to_message.from_user.id: await query.answer("❌ 非本人操作", show_alert=True); return
    target_username = await db_fetch_val("SELECT username FROM users WHERE pkid = $1", target_pkid)
    keyboard = [[InlineKeyboardButton("👍 推荐", callback_data=f"ask_tags:recommend:{target_pkid}"), InlineKeyboardButton("👎 警告", callback_data=f"ask_tags:block:{target_pkid}")], [InlineKeyboardButton("❌ 取消", callback_data="cancel_vote")]]; reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"您想如何评价 @{target_username}？", reply_markup=reply_markup)
@admin_required
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; await query.answer()
    keyboard = [[InlineKeyboardButton("🔧 管理底部按钮", callback_data="admin_menu_buttons")], [InlineKeyboardButton("« 返回主菜单", callback_data="show_private_main_menu")]]; reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("⚙️ **管理员面板**", reply_markup=reply_markup, parse_mode='Markdown')
@admin_required
async def admin_manage_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    buttons = await db_fetch_all("SELECT id, text, is_enabled FROM menu_buttons ORDER BY sort_order"); keyboard = []
    for btn in buttons: status_icon = "✅" if btn['is_enabled'] else "❌"; keyboard.append([InlineKeyboardButton(f"{status_icon} {btn['text']}", callback_data=f"admin_toggle_menu:{btn['id']}")])
    keyboard.append([InlineKeyboardButton("« 返回管理面板", callback_data="admin_panel")]); reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("🔧 **管理底部键盘按钮**\n点击按钮可切换其状态。\n用户需重发 /start 查看更新。", reply_markup=reply_markup)
@admin_required
async def admin_toggle_menu_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; _, button_id_str = query.data.split(':'); button_id = int(button_id_str)
    current_status = await db_fetch_val("SELECT is_enabled FROM menu_buttons WHERE id = $1", button_id)
    await db_execute("UPDATE menu_buttons SET is_enabled = $1 WHERE id = $2", not current_status, button_id); await admin_manage_menu(update, context)
async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.callback_query.answer()

# --- 主程序入口 (最终进化版) ---
async def post_init(app: Application):
    await database.init_db()
    logger.info("数据库初始化完成。")

async def main_async():
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token: raise ValueError("请设置 TELEGRAM_TOKEN 环境变量")

    application = ApplicationBuilder().token(token).post_init(post_init).build()

    # 添加所有处理器...
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("bang", show_leaderboard_handler))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^🚀 主菜单$'), show_private_main_menu))
    application.add_handler(MessageHandler(filters.TEXT & (filters.Regex(r'^🏆 排行榜$') | filters.Regex(r'^排行榜$')), show_leaderboard_handler))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^ℹ️ 帮助$'), help_command))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^@(\w+)$'), handle_mention_evaluation))
    application.add_handler(CallbackQueryHandler(show_private_main_menu, pattern=r'^show_private_main_menu$'))
    application.add_handler(CallbackQueryHandler(show_leaderboard_handler, pattern=r'^show_leaderboard_main$'))
    application.add_handler(CallbackQueryHandler(noop, pattern=r'^noop$'))
    application.add_handler(CallbackQueryHandler(ask_for_tags, pattern=r'^ask_tags:'))
    application.add_handler(CallbackQueryHandler(process_vote, pattern=r'^vote:'))
    application.add_handler(CallbackQueryHandler(cancel_vote, pattern=r'^cancel_vote$'))
    application.add_handler(CallbackQueryHandler(back_to_type_select, pattern=r'^back_to_type_select:'))
    application.add_handler(CallbackQueryHandler(admin_panel, pattern=r'^admin_panel$'))
    application.add_handler(CallbackQueryHandler(admin_manage_menu, pattern=r'^admin_menu_buttons$'))
    application.add_handler(CallbackQueryHandler(admin_toggle_menu_status, pattern=r'^admin_toggle_menu:'))
    application.add_handler(CallbackQueryHandler(show_favorites, pattern=r'^show_favorites:'))
    application.add_handler(CallbackQueryHandler(toggle_favorite, pattern=r'^toggle_favorite:'))
    application.add_handler(CallbackQueryHandler(remove_favorite_from_list, pattern=r'^remove_favorite:'))
    
    logger.info("机器人正在启动 polling...")
    await application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    # 启动健康检查服务器在一个单独的线程中
    health_thread = threading.Thread(target=run_health_check_server, daemon=True)
    health_thread.start()

    # 在主线程中运行异步的机器人
    asyncio.run(main_async())
