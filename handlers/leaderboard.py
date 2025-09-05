import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from math import ceil
import time

from database import db_fetch_all

logger = logging.getLogger(__name__)

PAGE_SIZE = 10
CACHE_KEY = "leaderboard_cache"
CACHE_DURATION = 300 # 缓存5分钟

# =============================================================================
# 命令处理器
# =============================================================================
async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """在群组或私聊中，通过命令或文本发送排行榜选项。"""
    text = "🏆 **排行榜**\n\n请选择您想查看的榜单："
    keyboard = [
        [InlineKeyboardButton("👍 推荐榜", callback_data="leaderboard_recommend_1"),
         InlineKeyboardButton("👎 警告榜", callback_data="leaderboard_block_1")],
        [InlineKeyboardButton("✨ 声望榜", callback_data="leaderboard_score_1"),
         InlineKeyboardButton("❤️ 人气榜", callback_data="leaderboard_favorites_1")]
    ]
    # 使用 reply_text 发送新消息，而不是 edit_message_text 编辑旧消息
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# =============================================================================
# 按钮回调处理器
# =============================================================================
async def show_leaderboard_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理从其他菜单跳转过来的排行榜请求（通过按钮点击）。"""
    query = update.callback_query
    text = "🏆 **排行榜**\n\n请选择您想查看的榜单："
    keyboard = [
        [InlineKeyboardButton("👍 推荐榜", callback_data="leaderboard_recommend_1"),
         InlineKeyboardButton("👎 警告榜", callback_data="leaderboard_block_1")],
        [InlineKeyboardButton("✨ 声望榜", callback_data="leaderboard_score_1"),
         InlineKeyboardButton("❤️ 人气榜", callback_data="leaderboard_favorites_1")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def get_leaderboard_page(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int):
    query = update.callback_query
    
    cached_data = context.bot_data.get(CACHE_KEY)
    current_time = time.time()

    if cached_data and (current_time - cached_data.get('timestamp', 0) < CACHE_DURATION):
        logger.info(f"从缓存加载排行榜数据 ({board_type})")
        all_users = cached_data.get('data', [])
    else:
        logger.info("重新生成排行榜数据并缓存")
        sql = """
        SELECT
            u.pkid,
            u.username,
            u.first_name,
            COALESCE(rec.count, 0) as recommend_count,
            COALESCE(blk.count, 0) as block_count,
            COALESCE(fav.count, 0) as favorite_count,
            (COALESCE(rec.count, 0) - COALESCE(blk.count, 0)) as score
        FROM users u
        LEFT JOIN (SELECT target_user_pkid, COUNT(*) as count FROM evaluations WHERE type = 'recommend' GROUP BY target_user_pkid) rec ON u.pkid = rec.target_user_pkid
        LEFT JOIN (SELECT target_user_pkid, COUNT(*) as count FROM evaluations WHERE type = 'block' GROUP BY target_user_pkid) blk ON u.pkid = blk.target_user_pkid
        LEFT JOIN (SELECT target_user_pkid, COUNT(*) as count FROM favorites GROUP BY target_user_pkid) fav ON u.pkid = fav.target_user_pkid
        WHERE u.id IS NOT NULL;
        """
        all_users = await db_fetch_all(sql)
        context.bot_data[CACHE_KEY] = {'timestamp': current_time, 'data': all_users}

    sort_key, title_icon, title_text = {
        'recommend': ('recommend_count', "👍", "推荐榜"),
        'block': ('block_count', "👎", "警告榜"),
        'score': ('score', "✨", "声望榜"),
        'favorites': ('favorite_count', "❤️", "人气榜")
    }.get(board_type, ('score', "✨", "声望榜"))

    sorted_users = sorted(all_users, key=lambda x: x.get(sort_key, 0), reverse=True)
    
    total_count = len(sorted_users)
    total_pages = ceil(total_count / PAGE_SIZE) if total_count > 0 else 1
    page = max(1, min(page, total_pages))
    offset = (page - 1) * PAGE_SIZE
    
    users_on_page = sorted_users[offset : offset + PAGE_SIZE]
    
    text = f"{title_icon} **{title_text}** (第 {page}/{total_pages} 页)\n\n"
    
    if not users_on_page:
        text += "_暂无数据_"
    else:
        rank_start = offset + 1
        for i, user in enumerate(users_on_page):
            rank = rank_start + i
            display_name = f"@{user['username']}" if user['username'] else (user.get('first_name') or f"用户{user['pkid']}")
            score = user.get(sort_key, 0)
            text += f"`{rank:2d}.` {display_name} - **{score}**\n"
            
    keyboard = []
    pagination = []
    if page > 1: pagination.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"leaderboard_{board_type}_{page-1}"))
    if page < total_pages: pagination.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"leaderboard_{board_type}_{page+1}"))
    if pagination: keyboard.append(pagination)
    
    keyboard.append([InlineKeyboardButton("🔙 返回榜单选择", callback_data="leaderboard_menu")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def clear_leaderboard_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if CACHE_KEY in context.bot_data:
        del context.bot_data[CACHE_KEY]
        logger.info("排行榜缓存已手动清除。")
        await query.answer("✅ 排行榜缓存已清除！", show_alert=True)
    else:
        await query.answer("ℹ️ 当前没有排行榜缓存。", show_alert=True)
    
    from .admin import leaderboard_panel
    await leaderboard_panel(update, context)
