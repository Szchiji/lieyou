import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import db_transaction, update_user_activity

logger = logging.getLogger(__name__)

# 缓存用户查询，避免频繁查询数据库
_user_cache = {}
_user_cache_timeout = {}
CACHE_TIMEOUT = 300  # 5分钟缓存

async def get_user_by_username(username: str) -> Optional[Dict]:
    """通过用户名获取用户信息，带缓存"""
    now = datetime.now()
    if username in _user_cache and _user_cache_timeout.get(username, now) > now:
        return _user_cache[username]
    
    async with db_transaction() as conn:
        user = await conn.fetchrow("SELECT id, username, first_name FROM users WHERE username = $1", username)
        result = dict(user) if user else None
        
        # 更新缓存
        _user_cache[username] = result
        _user_cache_timeout[username] = now + timedelta(seconds=CACHE_TIMEOUT)
        
        return result

async def handle_nomination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理群聊中@用户或查询用户的消息"""
    message = update.message
    text = message.text
    
    # 提取用户名
    username = None
    
    # 优先匹配 "查询 @username" 格式
    match = re.search(r'查询\s*@(\w{5,})', text)
    if match:
        username = match.group(1)
    else:
        # 匹配简单的 @username 格式
        match = re.search(r'@(\w{5,})', text)
        if match:
            username = match.group(1)
    
    if not username:
        return  # 没有找到用户名，不处理
    
    # 更新消息发送者的活动记录
    caller = update.effective_user
    await update_user_activity(caller.id, caller.username, caller.first_name)
    
    # 查找被提名的用户
    user = await get_user_by_username(username)
    if not user:
        await message.reply_text(f"未找到用户 @{username}，此人可能从未被评价过。")
        return
    
    target_id = user['id']
    
    # 防止自评
    if target_id == caller.id:
        await message.reply_text("自己评价自己？这可不符合神谕的法则。")
        return
    
    # 显示声誉摘要
    await show_reputation_summary(update, context, target_id, username)

async def handle_username_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理私聊中的用户名查询"""
    message = update.message
    text = message.text
    
    # 提取用户名
    match = re.search(r'查询\s+@(\w{5,})', text)
    if not match:
        await message.reply_text("请使用格式：查询 @用户名")
        return
    
    username = match.group(1)
    
    # 更新查询者的活动记录
    caller = update.effective_user
    await update_user_activity(caller.id, caller.username, caller.first_name)
    
    # 查找用户
    user = await get_user_by_username(username)
    if not user:
        await message.reply_text(f"未找到用户 @{username}")
        return
    
    target_id = user['id']
    
    # 防止自查
    if target_id == caller.id:
        await message.reply_text("查询自己的声誉？不如问问别人的看法。")
        return
    
    # 显示声誉摘要
    await show_reputation_summary(update, context, target_id, username)

async def show_reputation_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, target_id: int = None, username: str = None):
    """显示用户声誉摘要"""
    # 如果是通过回调查询调用的
    if update.callback_query and not target_id:
        data = update.callback_query.data
        if data.startswith("rep_summary_"):
            target_id = int(data.split("_")[2])
        await update.callback_query.answer()
    
    if not target_id:
        return
    
    # 获取声誉数据
    reputation_data = await get_reputation_data(target_id)
    
    # 获取用户信息
    if not username:
        async with db_transaction() as conn:
            user_info = await conn.fetchrow("SELECT username, first_name FROM users WHERE id = $1", target_id)
            if user_info:
                username = user_info['username']
                first_name = user_info['first_name']
            else:
                username = f"用户{target_id}"
                first_name = "未知用户"
    else:
        async with db_transaction() as conn:
            user_info = await conn.fetchrow("SELECT first_name FROM users WHERE id = $1", target_id)
            first_name = user_info['first_name'] if user_info else "未知用户"
    
    # 检查当前用户是否已投票
    caller_id = update.effective_user.id
    has_voted = await check_if_voted(caller_id, target_id)
    
    # 检查是否已收藏
    is_favorited = await check_if_favorited(caller_id, target_id)
    
    # 构建消息文本
    text = format_reputation_message(reputation_data, username, first_name)
    
    # 构建按钮
    keyboard = build_reputation_buttons(target_id, caller_id, has_voted, is_favorited)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # 发送或更新消息
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, 
            reply_markup=reply_markup, 
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            text, 
            reply_markup=reply_markup, 
            parse_mode=ParseMode.MARKDOWN
        )

async def get_reputation_data(target_id: int) -> Dict[str, Any]:
    """获取用户的完整声誉数据"""
    async with db_transaction() as conn:
        # 基本统计
        basic_stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total_votes,
                COUNT(*) FILTER (WHERE vote = 1) as positive_votes,
                COUNT(*) FILTER (WHERE vote = -1) as negative_votes,
                COUNT(DISTINCT voter_id) as unique_voters
            FROM reputation 
            WHERE target_id = $1
        """, target_id)
        
        # 获取标签统计
        tag_stats = await conn.fetch("""
            SELECT 
                t.name as tag_name,
                t.type as tag_type,
                COUNT(*) as count,
                COUNT(*) FILTER (WHERE r.vote = 1) as positive,
                COUNT(*) FILTER (WHERE r.vote = -1) as negative
            FROM reputation r
            JOIN tags t ON r.tag_id = t.id
            WHERE r.target_id = $1
            GROUP BY t.name, t.type
            ORDER BY count DESC
            LIMIT 5
        """, target_id)
        
        # 获取最近的评价
        recent_votes = await conn.fetch("""
            SELECT 
                r.vote,
                r.created_at,
                u.username as voter_username,
                u.first_name as voter_name,
                t.name as tag_name,
                t.type as tag_type
            FROM reputation r
            LEFT JOIN users u ON r.voter_id = u.id
            LEFT JOIN tags t ON r.tag_id = t.id
            WHERE r.target_id = $1
            ORDER BY r.created_at DESC
            LIMIT 5
        """, target_id)
        
        return {
            'basic_stats': dict(basic_stats) if basic_stats else {
                'total_votes': 0, 'positive_votes': 0, 'negative_votes': 0, 'unique_voters': 0
            },
            'tag_stats': [dict(tag) for tag in tag_stats],
            'recent_votes': [dict(vote) for vote in recent_votes]
        }

def format_reputation_message(reputation_data: Dict[str, Any], username: str, first_name: str) -> str:
    """格式化声誉信息消息"""
    basic = reputation_data['basic_stats']
    tag_stats = reputation_data['tag_stats']
    recent_votes = reputation_data['recent_votes']
    
    # 用户显示名（不使用特殊字体）
    display_name = first_name or f"@{username}" if username else "未知用户"
    
    # 声誉分数计算
    total_votes = basic['total_votes']
    positive_votes = basic['positive_votes']
    unique_voters = basic['unique_voters']
    
    if total_votes == 0:
        reputation_text = "🔮 此人尚无神谕记录"
        score_text = ""
    else:
        score = int((positive_votes / total_votes) * 100)
        
        # 根据分数显示不同的描述
        if score >= 90:
            reputation_text = f"✨ 声望如日中天 ({score}%)"
        elif score >= 75:
            reputation_text = f"🌟 德高望重 ({score}%)"
        elif score >= 60:
            reputation_text = f"⭐ 值得信赖 ({score}%)"
        elif score >= 40:
            reputation_text = f"⚠️ 褒贬不一 ({score}%)"
        elif score >= 25:
            reputation_text = f"❌ 声誉堪忧 ({score}%)"
        else:
            reputation_text = f"☠️ 声名狼藉 ({score}%)"
        
        score_text = f"\n📊 评价: 👍 {positive_votes} | 👎 {basic['negative_votes']} | 👥 {unique_voters}人"
    
    # 构建消息
    message = f"🔮 **{display_name}** 的神谕卷轴\n\n"
    message += reputation_text
    message += score_text
    
    # 添加热门标签
    if tag_stats:
        message += "\n\n🏷️ **标签印象**:\n"
        for tag in tag_stats[:3]:
            tag_emoji = "🏅" if tag['tag_type'] == 'recommend' else "⚠️"
            message += f"{tag_emoji} #{tag['tag_name']}: {tag['count']}次\n"
    
    # 添加最近评价
    if recent_votes:
        message += "\n📝 **最近神谕**:\n"
        for vote in recent_votes[:3]:
            vote_emoji = "👍" if vote['vote'] == 1 else "👎"
            voter_name = vote['voter_name'] or vote['voter_username'] or "匿名"
            tag_text = f" #{vote['tag_name']}" if vote['tag_name'] else ""
            date_text = vote['created_at'].strftime("%m-%d")
            message += f"{vote_emoji} {voter_name}{tag_text} ({date_text})\n"
    
    return message

def build_reputation_buttons(target_id: int, caller_id: int, has_voted: Dict, is_favorited: bool) -> List[List[InlineKeyboardButton]]:
    """构建声誉界面的按钮"""
    keyboard = []
    
    # 如果不是自己，显示投票按钮
    if caller_id != target_id:
        vote_row = []
        
        # 好评按钮
        if has_voted and has_voted.get('vote') == 1:
            vote_row.append(InlineKeyboardButton("✅ 已好评", callback_data=f"vote_up_{target_id}"))
        else:
            vote_row.append(InlineKeyboardButton("👍 好评", callback_data=f"vote_up_{target_id}"))
        
        # 差评按钮
        if has_voted and has_voted.get('vote') == -1:
            vote_row.append(InlineKeyboardButton("✅ 已差评", callback_data=f"vote_down_{target_id}"))
        else:
            vote_row.append(InlineKeyboardButton("👎 差评", callback_data=f"vote_down_{target_id}"))
        
        keyboard.append(vote_row)
    
    # 功能按钮行
    function_row = []
    function_row.append(InlineKeyboardButton("📊 详情", callback_data=f"rep_detail_{target_id}"))
    function_row.append(InlineKeyboardButton("👥 评价者", callback_data=f"rep_voters_menu_{target_id}"))
    
    # 收藏按钮（不能收藏自己）
    if caller_id != target_id:
        if is_favorited:
            function_row.append(InlineKeyboardButton("💖 已收藏", callback_data=f"query_fav_remove_{target_id}"))
        else:
            function_row.append(InlineKeyboardButton("🤍 收藏", callback_data=f"query_fav_add_{target_id}"))
    
    keyboard.append(function_row)
    
    # 返回按钮
    keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="back_to_help")])
    
    return keyboard

async def check_if_voted(voter_id: int, target_id: int) -> Optional[Dict]:
    """检查用户是否已经投票"""
    async with db_transaction() as conn:
        vote = await conn.fetchrow(
            "SELECT vote, tag_id FROM reputation WHERE voter_id = $1 AND target_id = $2",
            voter_id, target_id
        )
        return dict(vote) if vote else None

async def check_if_favorited(user_id: int, target_id: int) -> bool:
    """检查是否已收藏"""
    async with db_transaction() as conn:
        exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM favorites WHERE user_id = $1 AND target_id = $2)",
            user_id, target_id
        )
        return bool(exists)

async def show_reputation_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示详细的声誉信息"""
    query = update.callback_query
    await query.answer()
    
    target_id = int(query.data.split("_")[2])
    
    # 获取详细数据
    async with db_transaction() as conn:
        # 用户基本信息
        user_info = await conn.fetchrow(
            "SELECT username, first_name FROM users WHERE id = $1", target_id
        )
        
        # 按标签分组的详细统计
        tag_details = await conn.fetch("""
            SELECT 
                t.name as tag_name,
                t.type as tag_type,
                COUNT(*) as total_count,
                COUNT(*) FILTER (WHERE r.vote = 1) as positive_count,
                COUNT(*) FILTER (WHERE r.vote = -1) as negative_count
            FROM reputation r
            JOIN tags t ON r.tag_id = t.id
            WHERE r.target_id = $1
            GROUP BY t.name, t.type
            ORDER BY total_count DESC
        """, target_id)
        
        # 无标签的投票
        untagged = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total_count,
                COUNT(*) FILTER (WHERE vote = 1) as positive_count,
                COUNT(*) FILTER (WHERE vote = -1) as negative_count
            FROM reputation
            WHERE target_id = $1 AND tag_id IS NULL
        """, target_id)
    
    # 构建消息
    display_name = user_info['first_name'] or f"@{user_info['username']}" if user_info else "未知用户"
    message = f"🔍 **{display_name}** 的详细声誉分析\n\n"
    
    if not tag_details and (not untagged or untagged['total_count'] == 0):
        message += "暂无详细评价数据"
    else:
        # 推荐标签
        recommend_tags = [tag for tag in tag_details if tag['tag_type'] == 'recommend']
        if recommend_tags:
            message += "🏅 **推荐标签**:\n"
            for tag in recommend_tags:
                message += f"• #{tag['tag_name']}: 👍{tag['positive_count']} 👎{tag['negative_count']}\n"
            message += "\n"
        
        # 警告标签
        warning_tags = [tag for tag in tag_details if tag['tag_type'] == 'block']
        if warning_tags:
            message += "⚠️ **警告标签**:\n"
            for tag in warning_tags:
                message += f"• #{tag['tag_name']}: 👍{tag['positive_count']} 👎{tag['negative_count']}\n"
            message += "\n"
        
        # 无标签评价
        if untagged and untagged['total_count'] > 0:
            message += f"📝 **无标签评价**: 👍{untagged['positive_count']} 👎{untagged['negative_count']}\n"
    
    # 返回按钮
    keyboard = [[InlineKeyboardButton("🔙 返回", callback_data=f"rep_summary_{target_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def show_voters_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示查看评价者的菜单"""
    query = update.callback_query
    await query.answer()
    
    target_id = int(query.data.split("_")[3])
    
    message = "选择要查看的评价类型:"
    
    keyboard = [
        [
            InlineKeyboardButton("👍 好评者", callback_data=f"rep_voters_positive_{target_id}_1"),
            InlineKeyboardButton("👎 差评者", callback_data=f"rep_voters_negative_{target_id}_1")
        ],
        [InlineKeyboardButton("🔙 返回", callback_data=f"rep_summary_{target_id}")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(message, reply_markup=reply_markup)

async def show_reputation_voters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示评价者列表"""
    query = update.callback_query
    await query.answer()
    
    data_parts = query.data.split("_")
    vote_type = data_parts[2]  # positive 或 negative
    target_id = int(data_parts[3])
    page = int(data_parts[4]) if len(data_parts) > 4 else 1
    
    vote_value = 1 if vote_type == "positive" else -1
    per_page = 10
    offset = (page - 1) * per_page
    
    async with db_transaction() as conn:
        # 获取评价者列表
        voters = await conn.fetch("""
            SELECT 
                u.username, u.first_name,
                r.created_at,
                t.name as tag_name,
                t.type as tag_type
            FROM reputation r
            LEFT JOIN users u ON r.voter_id = u.id
            LEFT JOIN tags t ON r.tag_id = t.id
            WHERE r.target_id = $1 AND r.vote = $2
            ORDER BY r.created_at DESC
            LIMIT $3 OFFSET $4
        """, target_id, vote_value, per_page, offset)
        
        # 获取总数
        total_count = await conn.fetchval(
            "SELECT COUNT(*) FROM reputation WHERE target_id = $1 AND vote = $2",
            target_id, vote_value
        )
        
        # 获取用户名
        user_info = await conn.fetchrow(
            "SELECT username, first_name FROM users WHERE id = $1", target_id
        )
    
    # 构建消息
    display_name = user_info['first_name'] or f"@{user_info['username']}" if user_info else "未知用户"
    vote_type_text = "好评" if vote_type == "positive" else "差评"
    
    message = f"👥 **{display_name}** 的{vote_type_text}者列表\n\n"
    
    if not voters:
        message += "暂无数据"
    else:
        for i, voter in enumerate(voters, start=(page-1)*per_page + 1):
            voter_name = voter['first_name'] or voter['username'] or "匿名用户"
            tag_text = f" #{voter['tag_name']}" if voter['tag_name'] else ""
            date_text = voter['created_at'].strftime("%Y-%m-%d")
            message += f"{i}. {voter_name}{tag_text} - {date_text}\n"
    
    # 分页信息
    total_pages = (total_count + per_page - 1) // per_page
    if total_pages > 1:
        message += f"\n第 {page}/{total_pages} 页"
    
    # 构建按钮
    keyboard = []
    
    # 分页按钮
    if total_pages > 1:
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(
                "◀️ 上一页", 
                callback_data=f"rep_voters_{vote_type}_{target_id}_{page-1}"
            ))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(
                "▶️ 下一页", 
                callback_data=f"rep_voters_{vote_type}_{target_id}_{page+1}"
            ))
        keyboard.append(nav_buttons)
    
    # 返回按钮
    keyboard.append([InlineKeyboardButton("🔙 返回", callback_data=f"rep_voters_menu_{target_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理声誉相关的按钮回调"""
    query = update.callback_query
    data = query.data
    user = update.effective_user
    
    # 更新用户活动
    await update_user_activity(user.id, user.username, user.first_name)
    
    try:
        # 处理投票按钮
        if data.startswith("vote_"):
            await handle_vote_button(update, context)
        
        # 处理标签选择
        elif data.startswith("tag_"):
            await handle_tag_selection(update, context)
        
        # 其他回调由相应的函数处理
        
    except Exception as e:
        logger.error(f"处理按钮回调时出错: {e}", exc_info=True)
        await query.answer("处理请求时出错，请稍后再试", show_alert=True)

async def handle_vote_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理投票按钮"""
    query = update.callback_query
    data = query.data
    user = update.effective_user
    
    # 解析数据
    parts = data.split("_")
    vote_type = parts[1]  # up 或 down
    target_id = int(parts[2])
    
    # 防止自投票
    if user.id == target_id:
        await query.answer("不能给自己投票", show_alert=True)
        return
    
    vote_value = 1 if vote_type == "up" else -1
    
    # 检查是否已投票
    existing_vote = await check_if_voted(user.id, target_id)
    
    # 如果已投相同票，提示用户
    if existing_vote and existing_vote['vote'] == vote_value:
        await query.answer(f"您已经投过{'好' if vote_value == 1 else '差'}评了", show_alert=True)
        return
    
    # 获取可用标签
    tag_type = 'recommend' if vote_value == 1 else 'block'
    
    async with db_transaction() as conn:
        tags = await conn.fetch(
            "SELECT id, name FROM tags WHERE type = $1 ORDER BY name",
            tag_type
        )
    
    # 构建标签选择界面
    vote_text = "好评" if vote_value == 1 else "差评"
    message = f"请为您的{vote_text}选择一个标签（可选）:"
    
    keyboard = []
    
    # 添加标签按钮，每行2个
    for i in range(0, len(tags), 2):
        row = []
        for j in range(2):
            if i + j < len(tags):
                tag = tags[i + j]
                row.append(InlineKeyboardButton(
                    f"#{tag['name']}", 
                    callback_data=f"tag_{vote_value}_{target_id}_{tag['id']}"
                ))
        keyboard.append(row)
    
    # 无标签选项
    keyboard.append([InlineKeyboardButton("不选择标签", callback_data=f"tag_{vote_value}_{target_id}_0")])
    
    # 取消按钮
    keyboard.append([InlineKeyboardButton("取消", callback_data=f"rep_summary_{target_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(message, reply_markup=reply_markup)
    await query.answer()

async def handle_tag_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理标签选择"""
    query = update.callback_query
    data = query.data
    user = update.effective_user
    
    # 解析数据
    parts = data.split("_")
    vote_value = int(parts[1])  # 1 或 -1
    target_id = int(parts[2])
    tag_id = int(parts[3])  # 0表示无标签
    
    # 执行投票
    async with db_transaction() as conn:
        # 检查是否已有投票记录
        existing_vote = await conn.fetchval(
            "SELECT id FROM reputation WHERE voter_id = $1 AND target_id = $2",
            user.id, target_id
        )
        
        if existing_vote:
            # 更新现有投票
            if tag_id > 0:
                await conn.execute(
                    "UPDATE reputation SET vote = $1, tag_id = $2, created_at = NOW() WHERE voter_id = $3 AND target_id = $4",
                    vote_value, tag_id, user.id, target_id
                )
            else:
                await conn.execute(
                    "UPDATE reputation SET vote = $1, tag_id = NULL, created_at = NOW() WHERE voter_id = $2 AND target_id = $3",
                    vote_value, user.id, target_id
                )
        else:
            # 创建新投票
            if tag_id > 0:
                await conn.execute(
                    "INSERT INTO reputation (voter_id, target_id, vote, tag_id) VALUES ($1, $2, $3, $4)",
                    user.id, target_id, vote_value, tag_id
                )
            else:
                await conn.execute(
                    "INSERT INTO reputation (voter_id, target_id, vote) VALUES ($1, $2, $3)",
                    user.id, target_id, vote_value
                )
    
    # 清除缓存
    if target_id in _user_cache:
        del _user_cache[target_id]
    
    # 返回到声誉摘要
    await show_reputation_summary(update, context, target_id)
    await query.answer("✅ 投票成功", show_alert=True)
