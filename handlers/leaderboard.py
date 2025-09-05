import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from database import db_fetch_all, db_fetch_val, get_or_create_user

logger = logging.getLogger(__name__)

async def get_leaderboard_data(board_type: str, page: int, per_page: int = 10):
    """从数据库获取排行榜数据，适配新的 evaluations 表"""
    offset = (page - 1) * per_page
    
    # 核心改动：从 evaluations 表计算声望
    query = f"""
        WITH user_scores AS (
            SELECT
                target_user_pkid,
                SUM(CASE WHEN type = 'recommend' THEN 1 ELSE -1 END) as score
            FROM
                evaluations
            GROUP BY
                target_user_pkid
        )
        SELECT
            u.pkid,
            u.first_name,
            u.username,
            us.score
        FROM
            user_scores us
        JOIN
            users u ON us.target_user_pkid = u.pkid
        WHERE
            us.score != 0
        ORDER BY
            us.score {'DESC' if board_type == 'top' else 'ASC'}
        LIMIT $1 OFFSET $2;
    """
    
    total_query = "SELECT COUNT(*) FROM (SELECT 1 FROM evaluations GROUP BY target_user_pkid HAVING SUM(CASE WHEN type = 'recommend' THEN 1 ELSE -1 END) != 0) as active_users;"
    
    try:
        users = await db_fetch_all(query, per_page, offset)
        total_users = await db_fetch_val(total_query) or 0
        return users, total_users
    except Exception as e:
        logger.error(f"查询排行榜数据失败: {e}", exc_info=True)
        return [], 0

async def leaderboard_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int = 1):
    """显示排行榜菜单（无缓存版本）"""
    query = update.callback_query
    await get_or_create_user(user_id=query.from_user.id, username=query.from_user.username, first_name=query.from_user.first_name)
    
    per_page = 10
    users, total_users = await get_leaderboard_data(board_type, page, per_page)
    total_pages = max(1, (total_users + per_page - 1) // per_page)
    
    title = "🏆 好评榜" if board_type == "top" else "☠️ 差评榜"
    text = f"**{title} (第 {page}/{total_pages} 页)**\n\n"
    
    if not users:
        text += "这里空空如也..."
    else:
        rank_start = (page - 1) * per_page
        for i, user in enumerate(users):
            rank = rank_start + i + 1
            first_name = user.get('first_name')
            username = user.get('username')
            if first_name and first_name != username:
                display_name = f"{first_name} (@{username})" if username else first_name
            elif username:
                display_name = f"@{username}"
            else:
                display_name = f"用户 {user['pkid']}"
            score = user['score']
            line = f"`{rank}.` **{display_name}** (声望: `{score}`)\n"
            text += line

    keyboard_list = []
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"leaderboard_{board_type}_{page-1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"leaderboard_{board_type}_{page+1}"))
    
    if nav_row:
        keyboard_list.append(nav_row)

    keyboard_list.append([
        InlineKeyboardButton("🔄 刷新", callback_data=f"leaderboard_refresh_{board_type}_{page}"),
        InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard_list)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def refresh_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int):
    """刷新排行榜并重新显示"""
    query = update.callback_query
    await query.answer("排行榜已刷新！")
    # 直接重新调用 menu 函数即可，无需处理缓存
    await leaderboard_menu(update, context, board_type, page)

async def admin_clear_leaderboard_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """管理员手动清除所有排行榜缓存（功能保留，但仅作提示）"""
    query = update.callback_query
    await query.answer("缓存功能已移除，排行榜总是显示实时数据。", show_alert=True)
