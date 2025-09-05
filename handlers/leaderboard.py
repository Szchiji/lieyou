import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import db_fetch_all, db_fetch_one, db_fetchval, update_user_activity, get_setting

logger = logging.getLogger(__name__)

# 缓存设置
_leaderboard_cache = {}
_cache_expiry = {}
_cache_duration = timedelta(minutes=5) # 缓存5分钟

def clear_leaderboard_cache():
    """清空排行榜缓存"""
    global _leaderboard_cache, _cache_expiry
    _leaderboard_cache = {}
    _cache_expiry = {}
    logger.info("已清空排行榜缓存")

async def get_leaderboard_data(board_type: str, tag_filter: Optional[int] = None, page: int = 1) -> Tuple[List[Dict], int]:
    """获取排行榜数据（已修复）"""
    global _leaderboard_cache, _cache_expiry
    
    cache_key = f"{board_type}_{tag_filter}_{page}"
    now = datetime.now()
    
    if cache_key in _leaderboard_cache and _cache_expiry.get(cache_key, now) > now:
        logger.info(f"从缓存中获取排行榜数据: {cache_key}")
        return _leaderboard_cache[cache_key]
    
    logger.info(f"从数据库查询排行榜数据: {cache_key}")
    
    try:
        min_votes_str = await get_setting('min_votes_for_leaderboard')
        page_size_str = await get_setting('leaderboard_size')
        min_votes = int(min_votes_str) if min_votes_str and min_votes_str.isdigit() else 3
        page_size = int(page_size_str) if page_size_str and page_size_str.isdigit() else 10
    except (ValueError, TypeError):
        min_votes = 3
        page_size = 10
    
    offset = (page - 1) * page_size
    
    # **最终修复**: 确保所有对标签列的引用都是 `r.tag_id` (单数)
    base_query = """
        WITH user_stats AS (
            SELECT 
                u.id,
                u.username,
                u.first_name as display_name,
                COUNT(r.id) as total_votes,
                COUNT(r.id) FILTER (WHERE r.is_positive = TRUE) as positive_votes,
                COUNT(r.id) FILTER (WHERE r.is_positive = FALSE) as negative_votes,
                COUNT(DISTINCT r.voter_id) as unique_voters
            FROM users u
            JOIN reputations r ON u.id = r.target_id
    """
    
    params = []
    where_clauses = []
    
    if tag_filter:
        params.append(tag_filter)
        where_clauses.append(f"${len(params)} = ANY(r.tag_id)") # <--- 修正点
    
    if where_clauses:
        base_query += " WHERE " + " AND ".join(where_clauses)
        
    base_query += """
            GROUP BY u.id, u.username, u.first_name
            HAVING COUNT(r.id) >= ${param_idx}
        )
        SELECT 
            id, username, display_name, total_votes, positive_votes, negative_votes, unique_voters,
            CASE 
                WHEN total_votes > 0 THEN ROUND((positive_votes::float / total_votes) * 100)
                ELSE 0
            END as reputation_score
        FROM user_stats
    """.replace("${param_idx}", f"${len(params) + 1}")
    
    if board_type == "top":
        base_query += " ORDER BY reputation_score DESC, total_votes DESC"
    else:
        base_query += " ORDER BY reputation_score ASC, total_votes DESC"
    
    base_query += f" LIMIT ${len(params) + 2} OFFSET ${len(params) + 3}"
    
    final_params = params + [min_votes, page_size, offset]
    
    try:
        results = await db_fetch_all(base_query, *final_params)
        
        # **最终修复**: 修正获取总数的查询
        count_query_parts = [
            "SELECT COUNT(*) FROM (",
            "SELECT r.target_id FROM reputations r"
        ]
        count_params = []
        
        count_where_clauses = []
        if tag_filter:
            count_params.append(tag_filter)
            count_where_clauses.append(f"${len(count_params)} = ANY(r.tag_id)") # <--- 修正点
        
        if count_where_clauses:
            count_query_parts.append("WHERE " + " AND ".join(count_where_clauses))

        count_query_parts.append(f"GROUP BY r.target_id HAVING COUNT(r.id) >= ${len(count_params) + 1}")
        count_query_parts.append(") as filtered")
        
        count_query = " ".join(count_query_parts)
        final_count_params = count_params + [min_votes]

        total_count = await db_fetchval(count_query, *final_count_params) or 0
        
        leaderboard_data = [dict(row) for row in results]
        
        result = (leaderboard_data, total_count)
        _leaderboard_cache[cache_key] = result
        _cache_expiry[cache_key] = now + _cache_duration
        
        return result
        
    except Exception as e:
        logger.error(f"获取排行榜数据失败: {e}", exc_info=True)
        return ([], 0)

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示排行榜"""
    query = update.callback_query
    data = query.data
    
    await update_user_activity(update.effective_user.id, update.effective_user.username, update.effective_user.first_name)
    
    parts = data.split("_")
    # 兼容旧的回调格式 leaderboard_top_1 / leaderboard_bottom_tagselect_1
    if len(parts) > 2 and parts[2] == 'tagselect':
        board_type = parts[1]
        await show_tag_selection(update, context, board_type, 1)
        return

    # 新的回调格式 leaderboard_TYPE_ACTION_PARAM_PAGE
    # 例如: leaderboard_top_all_1, leaderboard_top_tag_123_1
    board_type = parts[1]
    action = parts[2] if len(parts) > 2 else 'all' # 默认为 all
    
    try:
        if action == "tagselect":
            page = int(parts[3]) if len(parts) > 3 else 1
            await show_tag_selection(update, context, board_type, page)
        elif action == "all":
            page = int(parts[3]) if len(parts) > 3 else 1
            await display_leaderboard(update, context, board_type, None, page)
        elif action == "tag":
            tag_id = int(parts[3])
            page = int(parts[4]) if len(parts) > 4 else 1
            await display_leaderboard(update, context, board_type, tag_id, page)
        else: # 兼容旧格式
            page = int(action)
            tag_id = int(parts[3]) if len(parts) > 3 else None
            await display_leaderboard(update, context, board_type, tag_id, page)
            
    except (ValueError, IndexError) as e:
        logger.error(f"解析排行榜回调数据失败: {data}, 错误: {e}")

async def show_tag_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int = 1):
    """显示标签选择页面"""
    query = update.callback_query
    await query.answer()
    
    per_page = 8
    offset = (page - 1) * per_page
    
    try:
        tags = await db_fetch_all("SELECT id, name, type FROM tags ORDER BY type = 'recommend' DESC, name LIMIT $1 OFFSET $2", per_page, offset)
        total_tags = await db_fetchval("SELECT COUNT(*) FROM tags") or 0
        total_pages = (total_tags + per_page - 1) // per_page if total_tags > 0 else 1
        
    except Exception as e:
        logger.error(f"获取标签失败: {e}", exc_info=True)
        await display_leaderboard(update, context, board_type, None, 1)
        return
    
    title = "🏆 英灵殿" if board_type == "top" else "☠️ 放逐深渊"
    message = f"**{title}** - 选择标签分类\n\n选择标签筛选排行榜，或查看全部："
    
    keyboard = [[InlineKeyboardButton("🌟 查看全部", callback_data=f"leaderboard_{board_type}_all_1")]]
    
    if tags:
        for i in range(0, len(tags), 2):
            row = [InlineKeyboardButton(f"{'🏅' if tag['type'] == 'recommend' else '⚠️'} {tag['name']}", callback_data=f"leaderboard_{board_type}_tag_{tag['id']}_1") for tag in tags[i:i+2]]
            keyboard.append(row)
    else:
        keyboard.append([InlineKeyboardButton("📝 暂无标签", callback_data="noop")])
    
    if total_pages > 1:
        nav_row = []
        if page > 1: nav_row.append(InlineKeyboardButton("◀️ 上一页", callback_data=f"leaderboard_{board_type}_tagselect_{page-1}"))
        if page < total_pages: nav_row.append(InlineKeyboardButton("▶️ 下一页", callback_data=f"leaderboard_{board_type}_tagselect_{page+1}"))
        if nav_row: keyboard.append(nav_row)
    
    opposite_type = "bottom" if board_type == "top" else "top"
    opposite_title = "☠️ 放逐深渊" if board_type == "top" else "🏆 英灵殿"
    keyboard.append([InlineKeyboardButton(f"🔄 切换到{opposite_title}", callback_data=f"leaderboard_{opposite_type}_tagselect_1")])
    keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"编辑标签选择消息失败: {e}")

async def display_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, tag_id: Optional[int], page: int = 1):
    """显示排行榜内容"""
    query = update.callback_query
    await query.answer()
    
    try:
        leaderboard_data, total_count = await get_leaderboard_data(board_type, tag_id, page)
        
        tag_name = None
        if tag_id:
            tag_info = await db_fetch_one("SELECT name, type FROM tags WHERE id = $1", tag_id)
            if tag_info: tag_name = f"{'🏅' if tag_info['type'] == 'recommend' else '⚠️'} {tag_info['name']}"
        
        title = "🏆 英灵殿" if board_type == "top" else "☠️ 放逐深渊"
        subtitle = f" - {tag_name}" if tag_name else ""
        message = f"**{title}{subtitle}**\n\n"
        
        if not leaderboard_data:
            message += "🌟 这里还很空旷，快来成为第一个上榜的人吧！"
        else:
            page_size_str = await get_setting('leaderboard_size')
            page_size = int(page_size_str) if page_size_str and page_size_str.isdigit() else 10
            start_rank = (page - 1) * page_size + 1
            
            for i, user in enumerate(leaderboard_data):
                rank = start_rank + i
                display_name = user.get('display_name') or f"@{user.get('username')}" if user.get('username') else f"用户{user.get('id')}"
                display_name = (display_name[:12] + "...") if len(display_name) > 15 else display_name
                
                rank_icon = f"{rank}."
                if board_type == "top":
                    if rank == 1: rank_icon = "🥇"
                    elif rank == 2: rank_icon = "🥈"
                    elif rank == 3: rank_icon = "🥉"
                
                score = user.get('reputation_score', 0)
                if score >= 90: level_icon = "⭐"
                elif score >= 75: level_icon = "✅"
                elif score >= 60: level_icon = "⚖️"
                elif score >= 40: level_icon = "⚠️"
                else: level_icon = "💀"
                
                message += f"{rank_icon} {level_icon} **{display_name}**\n   📊 {score}% ({user.get('positive_votes', 0)}👍/{user.get('negative_votes', 0)}👎)\n\n"
        
        page_size_str = await get_setting('leaderboard_size')
        page_size = int(page_size_str) if page_size_str and page_size_str.isdigit() else 10
        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1
        
        if total_pages > 1: message += f"第 {page}/{total_pages} 页 · 共 {total_count} 人"
        
        keyboard = []
        if total_pages > 1:
            nav_row = []
            callback_prefix = f"leaderboard_{board_type}_tag_{tag_id}" if tag_id else f"leaderboard_{board_type}_all"
            if page > 1: nav_row.append(InlineKeyboardButton("◀️ 上一页", callback_data=f"{callback_prefix}_{page-1}"))
            if page < total_pages: nav_row.append(InlineKeyboardButton("▶️ 下一页", callback_data=f"{callback_prefix}_{page+1}"))
            if nav_row: keyboard.append(nav_row)
        
        keyboard.append([InlineKeyboardButton("🏷️ 标签筛选", callback_data=f"leaderboard_{board_type}_tagselect_1")])
        keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        logger.error(f"显示排行榜失败: {e}", exc_info=True)
        error_message = "❌ 获取排行榜数据时出错，请稍后重试。"
        error_keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")]]
        try:
            await query.edit_message_text(error_message, reply_markup=InlineKeyboardMarkup(error_keyboard))
        except Exception as edit_error:
            logger.error(f"显示错误消息失败: {edit_error}")
