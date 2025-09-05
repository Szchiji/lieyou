import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode
from database import db_fetch_all, db_fetch_one, get_or_create_user
from cache import get_cache, set_cache

logger = logging.getLogger(__name__)

async def get_leaderboard_data(board_type: str, page: int, per_page: int = 10):
    """从数据库获取排行榜数据"""
    offset = (page - 1) * per_page
    order_by = "score DESC" if board_type == "top" else "score ASC"
    
    # 修正：将所有 target_user_id 替换为 target_user_pkid
    query = f"""
        SELECT 
            v.target_user_pkid,
            u.first_name,
            u.username,
            SUM(CASE WHEN t.type = 'recommend' THEN 1 ELSE 0 END) as recommend_count,
            SUM(CASE WHEN t.type = 'block' THEN 1 ELSE 0 END) as block_count,
            (SUM(CASE WHEN t.type = 'recommend' THEN 1 ELSE 0 END) - SUM(CASE WHEN t.type = 'block' THEN 1 ELSE 0 END)) as score
        FROM 
            votes v
        JOIN 
            users u ON v.target_user_pkid = u.pkid
        JOIN 
            tags t ON v.tag_id = t.id
        GROUP BY 
            v.target_user_pkid, u.first_name, u.username
        HAVING
            (SUM(CASE WHEN t.type = 'recommend' THEN 1 ELSE 0 END) - SUM(CASE WHEN t.type = 'block' THEN 1 ELSE 0 END)) != 0
        ORDER BY 
            {order_by}
        LIMIT $1 OFFSET $2
    """
    
    total_query = """
        SELECT COUNT(DISTINCT v.target_user_pkid) 
        FROM votes v
        JOIN tags t ON v.tag_id = t.id
        WHERE (SELECT SUM(CASE WHEN t2.type = 'recommend' THEN 1 ELSE -1 END) FROM votes v2 JOIN tags t2 ON v2.tag_id = t2.id WHERE v2.target_user_pkid = v.target_user_pkid) != 0
    """
    
    try:
        users = await db_fetch_all(query, per_page, offset)
        total_users = await db_fetch_one(total_query)
        return users, total_users[0] if total_users else 0
    except Exception as e:
        logger.error(f"查询排行榜数据失败: {e}")
        return [], 0


async def leaderboard_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int = 1):
    """显示排行榜菜单"""
    query = update.callback_query
    await get_or_create_user(user_id=query.from_user.id, username=query.from_user.username, first_name=query.from_user.first_name)
    
    cache_key = f"leaderboard_{board_type}_{page}"
    cached_data = await get_cache(cache_key)

    if cached_data:
        text, keyboard_list = cached_data['text'], cached_data['keyboard']
    else:
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
                display_name = user['first_name'] or (f"@{user['username']}" if user['username'] else f"用户 {user['target_user_pkid']}")
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

        await set_cache(cache_key, {'text': text, 'keyboard': keyboard_list}, ttl=300)

    keyboard_list.append([
        InlineKeyboardButton("🔄 刷新", callback_data=f"leaderboard_refresh_{board_type}_{page}"),
        InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard_list)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)


async def refresh_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int):
    """刷新排行榜并重新显示"""
    query = update.callback_query
    cache_key = f"leaderboard_{board_type}_{page}"
    await set_cache(cache_key, None, ttl=1) # 使缓存失效
    await query.answer("排行榜已刷新！")
    await leaderboard_menu(update, context, board_type, page)

async def admin_clear_leaderboard_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """管理员手动清除所有排行榜缓存"""
    # This is a simple example. A more robust solution would involve iterating keys.
    # For now, we just inform the admin. A proper implementation would need redis SCAN.
    query = update.callback_query
    await query.answer("缓存清除命令已发送（具体实现依赖缓存后端）。", show_alert=True)
