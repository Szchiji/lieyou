import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import db_fetch_all, db_fetchval
from .utils import schedule_message_deletion

logger = logging.getLogger(__name__)

ITEMS_PER_PAGE = 10
LEADERBOARD_CACHE = {} # 简单的内存缓存

def clear_leaderboard_cache():
    """清除排行榜缓存"""
    global LEADERBOARD_CACHE
    LEADERBOARD_CACHE = {}
    logger.info("排行榜缓存已清除。")

async def get_leaderboard_data(board_type: str):
    """
    获取并缓存排行榜数据。
    board_type: 'top' (好评榜) 或 'bottom' (差评榜)
    """
    if board_type in LEADERBOARD_CACHE:
        logger.debug(f"从缓存加载 {board_type} 排行榜。")
        return LEADERBOARD_CACHE[board_type]

    order = "DESC" if board_type == 'top' else "ASC"
    
    query = f"""
        SELECT 
            u.id,
            u.first_name,
            u.username,
            s.score
        FROM 
            users u
        JOIN 
            (
                SELECT 
                    target_user_id,
                    SUM(CASE WHEN t.type = 'recommend' THEN 1 ELSE -1 END) as score
                FROM 
                    votes v
                JOIN 
                    tags t ON v.tag_id = t.id
                GROUP BY 
                    v.target_user_id
            ) s ON u.id = s.target_user_id
        WHERE s.score != 0
        ORDER BY 
            s.score {order}, u.id ASC;
    """
    
    try:
        data = await db_fetch_all(query)
        LEADERBOARD_CACHE[board_type] = data
        logger.debug(f"已查询并缓存 {board_type} 排行榜数据。")
        return data
    except Exception as e:
        logger.error(f"查询排行榜数据失败: {e}")
        return []

async def leaderboard_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int):
    """显示好评榜或差评榜"""
    query = update.callback_query
    await query.answer()

    leaderboard_data = await get_leaderboard_data(board_type)
    
    if not leaderboard_data:
        # 确保返回主菜单的回调数据正确
        await query.edit_message_text("排行榜上还没有数据哦！", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")]]))
        return

    start_index = (page - 1) * ITEMS_PER_PAGE
    end_index = start_index + ITEMS_PER_PAGE
    paginated_data = leaderboard_data[start_index:end_index]
    
    total_pages = (len(leaderboard_data) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

    board_name = "好评榜" if board_type == 'top' else "差评榜"
    icon = "🏆" if board_type == 'top' else "☠️"
    
    text = f"{icon} **神谕者{board_name}** (第 {page}/{total_pages} 页)\n\n"
    
    rank_start = start_index + 1
    for i, user in enumerate(paginated_data, start=rank_start):
        display_name = user['first_name'] or (f"@{user['username']}" if user['username'] else f"用户{user['id']}")
        display_name = (display_name[:20] + '...') if len(display_name) > 20 else display_name
        
        rank_icon = ""
        if page == 1:
            if i == 1: rank_icon = "🥇"
            elif i == 2: rank_icon = "🥈"
            elif i == 3: rank_icon = "🥉"
            else: rank_icon = f"`{i: >2}`."
        else:
            rank_icon = f"`{i: >2}`."
            
        text += f"{rank_icon} {display_name}  **{user['score']}**\n"

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"leaderboard_{board_type}_{page-1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"leaderboard_{board_type}_{page+1}"))

    keyboard = []
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("🔄 刷新", callback_data=f"leaderboard_refresh_{board_type}_{page}")])
    # 确保返回主菜单的回调数据正确
    keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    # 确保在编辑消息时也处理可能的异常
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.warning(f"编辑排行榜消息失败: {e}")


async def refresh_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int):
    """刷新排行榜并重新显示"""
    query = update.callback_query
    clear_leaderboard_cache()
    await query.answer("排行榜已刷新！")
    await leaderboard_menu(update, context, board_type, page)

async def admin_clear_leaderboard_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """由管理员调用的清除缓存功能"""
    query = update.callback_query
    clear_leaderboard_cache()
    await query.answer("✅ 排行榜缓存已成功清除！", show_alert=True)
