import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import db_fetch_all, db_fetch_one, db_fetchval, update_user_activity

logger = logging.getLogger(__name__)

# 缓存设置
_leaderboard_cache = {}
_cache_expiry = {}
_cache_duration = timedelta(minutes=30)

def clear_leaderboard_cache():
    """清空排行榜缓存"""
    global _leaderboard_cache, _cache_expiry
    _leaderboard_cache = {}
    _cache_expiry = {}
    logger.info("已清空排行榜缓存")

async def get_leaderboard_data(board_type: str, tag_filter: Optional[int] = None, page: int = 1) -> Tuple[List[Dict], int]:
    """获取排行榜数据"""
    global _leaderboard_cache, _cache_expiry
    
    # 缓存键
    cache_key = f"{board_type}_{tag_filter}_{page}"
    now = datetime.now()
    
    # 检查缓存
    if cache_key in _leaderboard_cache and _cache_expiry.get(cache_key, now) > now:
        return _leaderboard_cache[cache_key]
    
    # 获取设置
    min_votes = int(await db_fetchval("SELECT value FROM settings WHERE key = 'min_votes_for_leaderboard'") or "3")
    page_size = int(await db_fetchval("SELECT value FROM settings WHERE key = 'leaderboard_size'") or "10")
    
    offset = (page - 1) * page_size
    
    # 构建查询
    base_query = """
        WITH user_stats AS (
            SELECT 
                u.id,
                u.username,
                u.first_name,
                COUNT(*) as total_votes,
                COUNT(*) FILTER (WHERE r.is_positive = TRUE) as positive_votes,
                COUNT(*) FILTER (WHERE r.is_positive = FALSE) as negative_votes,
                COUNT(DISTINCT r.voter_id) as unique_voters
            FROM users u
            JOIN reputations r ON u.id = r.target_id
    """
    
    params = [min_votes, page_size, offset]
    
    # 添加标签过滤
    if tag_filter:
        base_query += " WHERE $4 = ANY(r.tag_ids)"
        params.append(tag_filter)
    
    base_query += """
            GROUP BY u.id, u.username, u.first_name
            HAVING COUNT(*) >= $1
        )
        SELECT 
            id, username, first_name, total_votes, positive_votes, negative_votes, unique_voters,
            CASE 
                WHEN total_votes > 0 THEN ROUND((positive_votes::float / total_votes) * 100)
                ELSE 0
            END as reputation_score
        FROM user_stats
    """
    
    # 根据排行榜类型排序
    if board_type == "top":
        base_query += " ORDER BY reputation_score DESC, total_votes DESC"
    else:
        base_query += " ORDER BY reputation_score ASC, total_votes DESC"
    
    base_query += " LIMIT $2 OFFSET $3"
    
    # 执行查询
    results = await db_fetch_all(base_query, *params)
    
    # 获取总数
    count_query = """
        SELECT COUNT(*) FROM (
            SELECT r.target_id
            FROM reputations r
    """
    
    count_params = [min_votes]
    if tag_filter:
        count_query += " WHERE $2 = ANY(r.tag_ids)"
        count_params.append(tag_filter)
    
    count_query += """
            GROUP BY r.target_id
            HAVING COUNT(*) >= $1
        ) as filtered
    """
    
    total_count = await db_fetchval(count_query, *count_params)
    
    # 转换结果
    leaderboard_data = [dict(row) for row in results]
    
    # 缓存结果
    result = (leaderboard_data, total_count or 0)
    _leaderboard_cache[cache_key] = result
    _cache_expiry[cache_key] = now + _cache_duration
    
    return result

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示排行榜"""
    query = update.callback_query
    data = query.data
    
    # 更新用户活动
    await update_user_activity(update.effective_user.id, update.effective_user.username, update.effective_user.first_name)
    
    # 解析回调数据: leaderboard_TYPE_ACTION_PARAM_PAGE
    parts = data.split("_")
    board_type = parts[1]  # top 或 bottom
    action = parts[2]  # tagselect 或 display
    
    if action == "tagselect":
        page = int(parts[3]) if len(parts) > 3 else 1
        await show_tag_selection(update, context, board_type, page)
    elif action == "display":
        tag_id = int(parts[3]) if parts[3] != "all" else None
        page = int(parts[4]) if len(parts) > 4 else 1
        await display_leaderboard(update, context, board_type, tag_id, page)

async def show_tag_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int = 1):
    """显示标签选择页面"""
    query = update.callback_query
    await query.answer()
    
    per_page = 8
    offset = (page - 1) * per_page
    
    # 获取标签
    tags = await db_fetch_all("""
        SELECT id, name, type FROM tags
        ORDER BY type = 'recommend' DESC, name
        LIMIT $1 OFFSET $2
    """, per_page, offset)
    
    total_tags = await db_fetchval("SELECT COUNT(*) FROM tags")
    total_pages = (total_tags + per_page - 1) // per_page if total_tags > 0 else 1
    
    # 构建消息
    title = "🏆 英灵殿" if board_type == "top" else "☠️ 放逐深渊"
    message = f"*{title}* - 选择标签分类:"
    
    # 构建按钮
    keyboard = []
    
    # 全部选项
    keyboard.append([InlineKeyboardButton("🌐 全部", callback_data=f"leaderboard_{board_type}_display_all_1")])
    
    # 标签按钮
    for i in range(0, len(tags), 2):
        row = []
        for j in range(2):
            if i + j < len(tags):
                tag = tags[i + j]
                emoji = "🏅" if tag['type'] == 'recommend' else "⚠️"
                row.append(InlineKeyboardButton(
                    f"{emoji} {tag['name']}", 
                    callback_data=f"leaderboard_{board_type}_display_{tag['id']}_1"
                ))
        if row:
            keyboard.append(row)
    
    # 分页按钮
    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("◀️ 上一页", callback_data=f"leaderboard_{board_type}_tagselect_{page-1}"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("▶️ 下一页", callback_data=f"leaderboard_{board_type}_tagselect_{page+1}"))
        if nav_row:
            keyboard.append(nav_row)
    
    # 返回按钮
    keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def display_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, tag_id: Optional[int], page: int = 1):
    """显示排行榜内容"""
    query = update.callback_query
    await query.answer()
    
    # 获取数据
    leaderboard_data, total_count = await get_leaderboard_data(board_type, tag_id, page)
    
    # 获取标签名称
    tag_name = None
    if tag_id:
        tag_info = await db_fetch_one("SELECT name, type FROM tags WHERE id = $1", tag_id)
        if tag_info:
            emoji = "🏅" if tag_info['type'] == 'recommend' else "⚠️"
            tag_name = f"{emoji} {tag_info['name']}"
    
    # 构建消息
    title = "🏆 英灵殿" if board_type == "top" else "☠️ 放逐深渊"
    subtitle = f" - {tag_name}" if tag_name else ""
    message = f"*{title}{subtitle}*\n\n"
    
    if not leaderboard_data:
        message += "暂无符合条件的用户"
    else:
        page_size = int(await db_fetchval("SELECT value FROM settings WHERE key = 'leaderboard_size'") or "10")
        start_rank = (page - 1) * page_size + 1
        
        for i, user in enumerate(leaderboard_data):
            rank = start_rank + i
            
            # 用户显示名（使用标准字体）
            display_name = user['first_name'] or f"@{user['username']}" if user['username'] else f"用户{user['id']}"
            
            # 排名图标
            if board_type == "top" and rank <= 3:
                rank_icons = ["🥇", "🥈", "🥉"]
                rank_icon = rank_icons[rank-1] + " "
            elif board_type == "bottom" and rank <= 3:
                rank_icon = "💀 "
            else:
                rank_icon = ""
            
            # 声誉描述
            score = user['reputation_score']
            total_votes = user['total_votes']
            
            if board_type == "top":
                if score >= 90:
                    score_text = f"✨ {score}%"
                elif score >= 75:
                    score_text = f"🌟 {score}%"
                else:
                    score_text = f"⭐ {score}%"
            else:
                if score <= 10:
                    score_text = f"☠️ {score}%"
                elif score <= 25:
                    score_text = f"❌ {score}%"
                else:
                    score_text = f"⚠️ {score}%"
            
            message += f"{rank_icon}{rank}. {display_name} - {score_text} ({total_votes}票)\n"
    
    # 分页信息
    page_size = int(await db_fetchval("SELECT value FROM settings WHERE key = 'leaderboard_size'") or "10")
    total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1
    
    if total_pages > 1:
        message += f"\n第 {page}/{total_pages} 页"
    
    # 构建按钮
    keyboard = []
    
    # 分页按钮
    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("◀️ 上一页", callback_data=f"leaderboard_{board_type}_display_{tag_id or 'all'}_{page-1}"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("▶️ 下一页", callback_data=f"leaderboard_{board_type}_display_{tag_id or 'all'}_{page+1}"))
        if nav_row:
            keyboard.append(nav_row)
    
    # 切换排行榜按钮
    opposite_type = "bottom" if board_type == "top" else "top"
    opposite_title = "☠️ 放逐深渊" if board_type == "top" else "🏆 英灵殿"
    keyboard.append([InlineKeyboardButton(f"查看{opposite_title}", callback_data=f"leaderboard_{opposite_type}_tagselect_1")])
    
    # 功能按钮
    keyboard.append([
        InlineKeyboardButton("🔍 选择标签", callback_data=f"leaderboard_{board_type}_tagselect_1"),
        InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
