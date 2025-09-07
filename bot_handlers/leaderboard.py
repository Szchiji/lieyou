import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from math import ceil

from database import db_fetch_all, is_admin
from .utils import membership_required
from . import admin as admin_handlers

logger = logging.getLogger(__name__)

PAGE_SIZE = 10
CACHE_SECONDS = 300  # 5分钟缓存

async def get_leaderboard_data(context: ContextTypes.DEFAULT_TYPE, leaderboard_type: str):
    """从数据库获取并缓存排行榜数据。"""
    cache_key = f"leaderboard_{leaderboard_type}"
    cached_data = context.bot_data.get(cache_key)
    
    if cached_data and (datetime.now() - cached_data['timestamp']).total_seconds() < CACHE_SECONDS:
        logger.info(f"使用缓存的 '{leaderboard_type}' 排行榜数据。")
        return cached_data['data']

    logger.info(f"重新生成 '{leaderboard_type}' 排行榜数据。")
    
    if leaderboard_type == 'recommend':
        query = """
            SELECT u.username, COUNT(e.pkid) as count
            FROM evaluations e JOIN users u ON e.target_user_pkid = u.pkid
            WHERE e.type = 'recommend'
            GROUP BY u.username HAVING COUNT(e.pkid) > 0
            ORDER BY count DESC, u.username LIMIT 50;
        """
    elif leaderboard_type == 'block':
        query = """
            SELECT u.username, COUNT(e.pkid) as count
            FROM evaluations e JOIN users u ON e.target_user_pkid = u.pkid
            WHERE e.type = 'block'
            GROUP BY u.username HAVING COUNT(e.pkid) > 0
            ORDER BY count DESC, u.username LIMIT 50;
        """
    elif leaderboard_type == 'score':
        query = """
            SELECT u.username, 
                   (COUNT(CASE WHEN e.type = 'recommend' THEN 1 END) - COUNT(CASE WHEN e.type = 'block' THEN 1 END)) as score
            FROM evaluations e JOIN users u ON e.target_user_pkid = u.pkid
            GROUP BY u.username
            HAVING (COUNT(CASE WHEN e.type = 'recommend' THEN 1 END) - COUNT(CASE WHEN e.type = 'block' THEN 1 END)) != 0
            ORDER BY score DESC, u.username LIMIT 50;
        """
    elif leaderboard_type == 'popularity':
        query = """
            SELECT u.username, COUNT(f.pkid) as count
            FROM favorites f JOIN users u ON f.target_user_pkid = u.pkid
            GROUP BY u.username HAVING COUNT(f.pkid) > 0
            ORDER BY count DESC, u.username LIMIT 50;
        """
    else:
        return []

    data = await db_fetch_all(query)
    context.bot_data[cache_key] = {'data': data, 'timestamp': datetime.now()}
    return data

@membership_required
async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    响应 /bang 命令。
    - 在群组中，引导用户到私聊。
    - 在私聊中，直接显示排行榜菜单。
    """
    # 如果命令来自于群组或超级群组
    if update.message and update.message.chat.type in ['group', 'supergroup']:
        bot_username = context.bot.username
        private_chat_button = InlineKeyboardMarkup([
            [InlineKeyboardButton("👉 前往私聊查看排行榜", url=f"https://t.me/{bot_username}?start=bang")]
        ])
        await update.message.reply_text(
            "为保持群内整洁，排行榜功能请在私聊窗口查看。",
            reply_markup=private_chat_button
        )
        return
    
    # 如果是私聊（或通过 deep-linking 启动），直接显示排行榜菜单
    await show_leaderboard_menu(update, context)

@membership_required
async def show_leaderboard_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示排行榜类型的选择菜单 (此函数现在只应在私聊中被调用)。"""
    text = "🏆 **排行榜**\n\n请选择您想查看的榜单："
    keyboard = [
        [
            InlineKeyboardButton("👍 推荐榜", callback_data="leaderboard_recommend_1"),
            InlineKeyboardButton("👎 避雷榜", callback_data="leaderboard_block_1")
        ],
        [
            InlineKeyboardButton("✨ 声望榜", callback_data="leaderboard_score_1"),
            InlineKeyboardButton("❤️ 人气榜", callback_data="leaderboard_popularity_1")
        ],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

@membership_required
async def get_leaderboard_page(update: Update, context: ContextTypes.DEFAULT_TYPE, leaderboard_type: str, page: int):
    """显示特定类型排行榜的某一页。"""
    query = update.callback_query
    await query.answer()

    data = await get_leaderboard_data(context, leaderboard_type)

    if not data:
        await query.edit_message_text("此榜单暂时没有数据哦。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回榜单选择", callback_data="leaderboard_menu")]]))
        return

    total_pages = ceil(len(data) / PAGE_SIZE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * PAGE_SIZE
    page_data = data[offset : offset + PAGE_SIZE]

    titles = {
        'recommend': '👍 推荐榜', 'block': '👎 避雷榜',
        'score': '✨ 声望榜', 'popularity': '❤️ 人气榜'
    }
    title = titles.get(leaderboard_type, "排行榜")
    
    text = f"**{title}** \\(第 {page}/{total_pages} 页\\)\n\n"
    rank_start = offset + 1
    
    for i, row in enumerate(page_data):
        username = row['username'].replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace('`', '\\`')
        value = row.get('count') or row.get('score')
        text += f"`{rank_start + i:2d}\\.` @{username} \\- **{value}**\n"
    
    pagination = []
    if page > 1:
        pagination.append(InlineKeyboardButton("⬅️", callback_data=f"leaderboard_{leaderboard_type}_{page-1}"))
    if page < total_pages:
        pagination.append(InlineKeyboardButton("➡️", callback_data=f"leaderboard_{leaderboard_type}_{page+1}"))
    
    keyboard = []
    if pagination:
        keyboard.append(pagination)
    keyboard.append([InlineKeyboardButton("🔙 返回榜单选择", callback_data="leaderboard_menu")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)


async def clear_leaderboard_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """由管理员调用的清除排行榜缓存的功能。"""
    if not await is_admin(update.effective_user.id):
        await update.callback_query.answer("🚫 您不是管理员。", show_alert=True)
        return
        
    for key in list(context.bot_data.keys()):
        if key.startswith("leaderboard_"):
            del context.bot_data[key]
    
    logger.info(f"管理员 {update.effective_user.id} 已清除所有排行榜缓存。")
    await update.callback_query.answer("✅ 所有排行榜缓存已清除！", show_alert=True)
    
    # 刷新管理面板
    await admin_handlers.leaderboard_panel(update, context)
