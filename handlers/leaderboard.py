import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import db_fetch_all, db_fetch_one
from handlers.admin import is_admin

logger = logging.getLogger(__name__)

# 缓存排行榜数据，减少数据库查询
# 格式: {type_tag_page: {'data': data, 'timestamp': datetime}}
_leaderboard_cache: Dict[str, Dict] = {}
CACHE_TTL = timedelta(minutes=10)  # 缓存有效期

def clear_leaderboard_cache():
    """清空排行榜缓存"""
    global _leaderboard_cache
    _leaderboard_cache = {}
    logger.info("排行榜缓存已清空")

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示排行榜"""
    query = update.callback_query
    await query.answer()
    
    # 解析回调数据格式: leaderboard_[top/bottom]_[tagselect/tagid]_[page]
    parts = query.data.split('_')
    if len(parts) < 4:
        await query.edit_message_text("❌ 排行榜数据格式错误")
        return
    
    # 提取排行榜类型和页码
    board_type = parts[1]  # top 或 bottom
    tag_part = parts[2]   # tagselect 或具体的标签ID
    try:
        page = int(parts[3])
    except ValueError:
        page = 1
    
    if tag_part == "tagselect":
        # 显示标签选择菜单
        await show_tag_selection(update, context, board_type, page)
    elif tag_part.isdigit() or tag_part == "all":
        # 显示具体排行榜
        tag_id = int(tag_part) if tag_part.isdigit() else None
        user_id = update.effective_user.id
        show_self = await is_self_ranking(user_id)
        await display_leaderboard(update, context, board_type, tag_id, page, show_self)
    else:
        await query.edit_message_text("❌ 无效的排行榜参数")

async def show_tag_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int):
    """显示标签选择菜单"""
    query = update.callback_query
    
    # 获取标签列表
    tag_type = "recommend" if board_type == "top" else "block"
    tags = await get_tags_for_selection(tag_type)
    
    # 分页处理
    page_size = 5
    total_pages = (len(tags) + page_size - 1) // page_size if tags else 1
    page = min(max(page, 1), total_pages)
    
    start_idx = (page - 1) * page_size
    end_idx = min(start_idx + page_size, len(tags))
    current_page_tags = tags[start_idx:end_idx] if tags else []
    
    # 构建键盘
    keyboard = []
    for tag_id, tag_content in current_page_tags:
        keyboard.append([
            InlineKeyboardButton(tag_content, callback_data=f"leaderboard_{board_type}_{tag_id}_1")
        ])
    
    # 添加"显示所有"按钮
    keyboard.append([
        InlineKeyboardButton("显示所有", callback_data=f"leaderboard_{board_type}_all_1")
    ])
    
    # 添加分页按钮
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("« 上一页", callback_data=f"leaderboard_{board_type}_tagselect_{page-1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("下一页 »", callback_data=f"leaderboard_{board_type}_tagselect_{page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # 添加返回按钮
    keyboard.append([InlineKeyboardButton("« 返回", callback_data="back_to_help")])
    
    # 构建消息文本
    title = "🏆 英灵殿" if board_type == "top" else "☠️ 放逐深渊"
    text = f"{title} - 请选择一个标签查看相关排行:"
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=text, reply_markup=reply_markup)

async def display_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, tag_id: Optional[int], page: int, show_self: bool = False):
    """显示排行榜内容"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    # 设置标题和排序方式
    if board_type == "top":
        title = "🏆 英灵殿"
        sort_order = "DESC"
    else:  # bottom
        title = "☠️ 放逐深渊"
        sort_order = "ASC"
    
    # 获取标签名称
    tag_name = "全部标签"
    if tag_id is not None:
        tag_data = await db_fetch_one("SELECT content, tag_type FROM tags WHERE id = $1", tag_id)
        if tag_data:
            tag_name = tag_data['content']
    
    # 检查缓存
    cache_key = f"{board_type}_{tag_id}_{page}"
    now = datetime.now()
    cached_data = _leaderboard_cache.get(cache_key)
    
    if cached_data and (now - cached_data['timestamp']) < CACHE_TTL:
        # 使用缓存数据
        leaderboard_data = cached_data['data']
    else:
        # 从数据库获取数据
        leaderboard_data = await fetch_leaderboard_data(board_type, tag_id, sort_order, page, show_self, user_id)
        # 更新缓存
        _leaderboard_cache[cache_key] = {
            'data': leaderboard_data,
            'timestamp': now
        }
    
    # 构建排行榜文本
    text = f"**{title}** - {tag_name}\n\n"
    
    # 添加排行榜数据
    if not leaderboard_data:
        text += "暂无数据"
    else:
        for rank, (target_id, username, vote_count) in enumerate(leaderboard_data, 1):
            # 不使用特殊字体显示用户名
            display_name = username or f"用户{target_id}"
            if target_id == user_id:
                display_name = f"👤 {display_name} (你)"  # 标记当前用户
            
            text += f"{rank}. {display_name}: {vote_count}次点评\n"
    
    # 构建键盘
    keyboard = []
    
    # 返回到标签选择
    keyboard.append([
        InlineKeyboardButton("« 返回标签选择", callback_data=f"leaderboard_{board_type}_tagselect_1")
    ])
    
    # 添加"查看我的排名"按钮，如果尚未显示
    if not show_self:
        keyboard.append([
            InlineKeyboardButton("👤 查看我的排名", callback_data=f"leaderboard_{board_type}_{tag_id if tag_id else 'all'}_1_self")
        ])
    
    # 添加返回主菜单按钮
    keyboard.append([InlineKeyboardButton("« 返回主菜单", callback_data="back_to_help")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def get_tags_for_selection(tag_type: str) -> List[Tuple[int, str]]:
    """获取指定类型的标签列表"""
    try:
        query = "SELECT id, content FROM tags WHERE tag_type = $1 ORDER BY content"
        rows = await db_fetch_all(query, tag_type)
        return [(row['id'], row['content']) for row in rows]
    except Exception as e:
        logger.error(f"获取标签列表失败: {e}", exc_info=True)
        return []

async def fetch_leaderboard_data(board_type: str, tag_id: Optional[int], sort_order: str, page: int, show_self: bool, user_id: int) -> List[Tuple[int, str, int]]:
    """从数据库获取排行榜数据"""
    try:
        page_size = 10
        offset = (page - 1) * page_size
        
        # 构建查询条件
        where_clause = ""
        params = []
        
        if tag_id is not None:
            where_clause = "WHERE r.tag_id = $1"
            params.append(tag_id)
        
        # 如果要显示用户自己的排名
        if show_self:
            query = f"""
            WITH user_stats AS (
                SELECT 
                    r.target_id,
                    u.username,
                    COUNT(*) as vote_count
                FROM reputation r
                LEFT JOIN users u ON r.target_id = u.id
                {where_clause}
                GROUP BY r.target_id, u.username
            )
            SELECT 
                target_id, 
                username, 
                vote_count
            FROM user_stats
            WHERE target_id = ${'$' + str(len(params) + 1)}
            """
            params.append(user_id)
        else:
            query = f"""
            SELECT 
                r.target_id,
                u.username,
                COUNT(*) as vote_count
            FROM reputation r
            LEFT JOIN users u ON r.target_id = u.id
            {where_clause}
            GROUP BY r.target_id, u.username
            ORDER BY vote_count {sort_order}, r.target_id
            LIMIT {page_size} OFFSET {offset}
            """
        
        rows = await db_fetch_all(query, *params)
        return [(row['target_id'], row['username'], row['vote_count']) for row in rows]
    except Exception as e:
        logger.error(f"获取排行榜数据失败: {e}", exc_info=True)
        return []

async def is_self_ranking(user_id: int) -> bool:
    """检查是否显示自己的排名"""
    # 这个函数在查询字符串中包含_self时返回True
    return False
