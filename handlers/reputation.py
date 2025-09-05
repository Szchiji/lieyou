import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import (
    db_transaction, db_fetch_one, db_fetch_all, db_fetchval,
    update_user_activity, get_setting
)
from .utils import schedule_message_deletion

logger = logging.getLogger(__name__)

# --- 主查询入口 ---

async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理对用户声誉的查询 (通过 @username, user_id, 或回复消息)"""
    query_user = update.effective_user
    await update_user_activity(query_user.id, query_user.username, query_user.first_name)

    target_user_id = None
    target_username = None

    # 1. 检查是否回复消息
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        target_user_id = target_user.id
        await update_user_activity(target_user.id, target_user.username, target_user.first_name)

    # 2. 检查消息文本中的 @username 或 user_id
    else:
        # 移除了 '查询' 关键字要求，直接匹配 @ 或数字
        match = re.search(r'@(\w+)|(\d{5,})', update.message.text)
        if match:
            if match.group(1): # @username
                target_username = match.group(1)
                user_data = await db_fetch_one("SELECT id FROM users WHERE username = $1", target_username)
                if user_data:
                    target_user_id = user_data['id']
                else:
                    await update.message.reply_text(f"我还没有关于 @{target_username} 的信息。")
                    return
            elif match.group(2): # user_id
                try:
                    target_user_id = int(match.group(2))
                    # 验证用户是否存在
                    if not await db_fetch_one("SELECT id FROM users WHERE id = $1", target_user_id):
                        await update.message.reply_text(f"我还没有关于用户ID {target_user_id} 的信息。")
                        return
                except ValueError:
                    pass # 不是有效的ID

    if not target_user_id:
        # 如果没有明确目标，显示帮助或自己的信息
        await show_help_or_self_rep(update, context)
        return

    # 生成并发送声誉卡片
    await send_reputation_card(update, context, target_user_id)

async def show_help_or_self_rep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """在没有明确查询目标时，显示帮助信息或用户自己的声誉"""
    # 在这个版本，我们简化为只显示帮助信息
    start_message = await get_setting('start_message', "欢迎使用神谕者机器人！")
    keyboard = [
        [InlineKeyboardButton("🏆 好评榜", callback_data="leaderboard_top_1")],
        [InlineKeyboardButton("☠️ 差评榜", callback_data="leaderboard_bottom_1")],
        [InlineKeyboardButton("❤️ 我的收藏", callback_data="my_favorites_1")],
        [InlineKeyboardButton("⚙️ 管理面板", callback_data="admin_settings_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    sent_message = await update.message.reply_text(start_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    await schedule_message_deletion(context, sent_message.chat.id, sent_message.message_id)

# --- 声誉卡片生成与发送 ---

async def send_reputation_card(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int):
    """生成并发送指定用户的声誉卡片"""
    try:
        card_data = await build_reputation_card_data(target_user_id)
        if not card_data:
            await update.message.reply_text("无法获取该用户的声誉信息。")
            return

        is_favorite = await db_fetch_one("SELECT 1 FROM favorites WHERE user_id = $1 AND target_user_id = $2", update.effective_user.id, target_user_id)
        
        text, keyboard = format_reputation_card(card_data, is_favorite)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        sent_message = await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        
        # 安排消息自动删除
        await schedule_message_deletion(context, sent_message.chat.id, sent_message.message_id)

    except Exception as e:
        logger.error(f"发送声誉卡片失败 (用户ID: {target_user_id}): {e}", exc_info=True)
        await update.message.reply_text("❌ 生成声誉卡片时出错。")

async def build_reputation_card_data(target_user_id: int):
    """从数据库收集构建声誉卡片所需的数据"""
    query = """
    WITH user_info AS (
        SELECT id, first_name, username FROM users WHERE id = $1
    ),
    votes_summary AS (
        SELECT
            t.type,
            t.name,
            COUNT(v.id) as count
        FROM votes v
        JOIN tags t ON v.tag_id = t.id
        WHERE v.target_user_id = $1
        GROUP BY t.type, t.name
    ),
    recommend_votes AS (
        SELECT name, count FROM votes_summary WHERE type = 'recommend' ORDER BY count DESC, name ASC
    ),
    block_votes AS (
        SELECT name, count FROM votes_summary WHERE type = 'block' ORDER BY count DESC, name ASC
    )
    SELECT
        (SELECT * FROM user_info) as user_data,
        (SELECT COALESCE(json_agg(reco), '[]'::json) FROM recommend_votes reco) as recommend_tags,
        (SELECT COALESCE(json_agg(bl), '[]'::json) FROM block_votes bl) as block_tags;
    """
    data = await db_fetch_one(query, target_user_id)
    
    if not data or not data['user_data']:
        # 如果用户在votes表里有记录但在users表里没有，需要补充信息
        user_in_votes = await db_fetchval("SELECT 1 FROM votes WHERE target_user_id = $1 LIMIT 1", target_user_id)
        if user_in_votes:
            # 这是一个边缘情况，最好有一个用户数据同步机制
            await update_user_activity(target_user_id, None, f"用户{target_user_id}")
            # 再次尝试获取数据
            data = await db_fetch_one(query, target_user_id)
            if not data or not data['user_data']:
                return None
        else:
            return None # 用户确实不存在

    return data

def format_reputation_card(data: dict, is_favorite: bool):
    """将数据格式化为文本和键盘布局"""
    user_data = data['user_data']
    recommend_tags = data['recommend_tags']
    block_tags = data['block_tags']

    display_name = user_data['first_name'] or (f"@{user_data['username']}" if user_data['username'] else f"用户{user_data['id']}")
    
    total_recommend = sum(tag['count'] for tag in recommend_tags)
    total_block = sum(tag['count'] for tag in block_tags)
    net_score = total_recommend - total_block

    # 构建文本
    text = f"**声誉档案 - {display_name}**\n"
    text += f"综合评价: **{net_score}** (👍{total_recommend} / 👎{total_block})\n\n"

    if recommend_tags:
        text += "👍 **收到好评:**\n"
        text += "、".join([f"{tag['name']} ({tag['count']})" for tag in recommend_tags]) + "\n\n"
    
    if block_tags:
        text += "👎 **收到差评:**\n"
        text += "、".join([f"{tag['name']} ({tag['count']})" for tag in block_tags]) + "\n\n"

    if not recommend_tags and not block_tags:
        text += "*暂无评价记录。*\n\n"

    text += f"_(用户ID: `{user_data['id']}`)_"

    # 构建键盘
    favorite_text = "❤️ 已收藏" if is_favorite else "🤍 添加收藏"
    favorite_callback = "remove_favorite_" if is_favorite else "add_favorite_"
    
    keyboard = [
        [
            InlineKeyboardButton("👍 给好评", callback_data=f"vote_recommend_{user_data['id']}_1"),
            InlineKeyboardButton("👎 给差评", callback_data=f"vote_block_{user_data['id']}_1")
        ],
        [
            InlineKeyboardButton(favorite_text, callback_data=f"{favorite_callback}{user_data['id']}"),
            InlineKeyboardButton("📊 统计", callback_data=f"stats_user_{user_data['id']}")
        ]
    ]
    return text, keyboard

# --- 投票处理 ---

async def vote_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int, vote_type: str, page: int):
    """显示好评或差评的标签菜单以供选择"""
    query = update.callback_query
    await query.answer()

    tags = await db_fetch_all("SELECT name FROM tags WHERE type = $1 ORDER BY name", vote_type)
    if not tags:
        await query.answer("管理员尚未设置任何标签！", show_alert=True)
        return
        
    vote_type_text = "好评" if vote_type == "recommend" else "差评"
    
    keyboard = []
    for tag in tags:
        keyboard.append([InlineKeyboardButton(tag['name'], callback_data=f"process_vote_{target_user_id}_{tag['name']}")])
    
    keyboard.append([InlineKeyboardButton("🔙 返回声誉卡片", callback_data=f"back_to_rep_card_{target_user_id}")])
    
    await query.edit_message_text(f"请为该用户选择一个**{vote_type_text}**标签：", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def process_vote(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int, tag_name: str):
    """处理用户的投票选择，并更新数据库"""
    query = update.callback_query
    voter_user_id = query.from_user.id

    if voter_user_id == target_user_id:
        await query.answer("❌ 你不能给自己投票。", show_alert=True)
        return

    try:
        async with db_transaction() as conn:
            # 获取tag_id
            tag = await conn.fetchrow("SELECT id, type FROM tags WHERE name = $1", tag_name)
            if not tag:
                await query.answer("❌ 标签不存在，可能已被管理员删除。", show_alert=True)
                return
            tag_id = tag['id']
            tag_type = tag['type']

            # 检查是否已存在相同投票
            existing_vote = await conn.fetchval(
                "SELECT id FROM votes WHERE voter_user_id = $1 AND target_user_id = $2 AND tag_id = $3",
                voter_user_id, target_user_id, tag_id
            )
            if existing_vote:
                await query.answer("❌ 你已经使用这个标签评价过该用户了。", show_alert=True)
                return

            # 插入新投票
            await conn.execute(
                """
                INSERT INTO votes (voter_user_id, target_user_id, tag_id, message_id, chat_id)
                VALUES ($1, $2, $3, $4, $5)
                """,
                voter_user_id, target_user_id, tag_id, query.message.message_id, query.message.chat.id
            )
            
            vote_type_text = "好评" if tag_type == "recommend" else "差评"
            await query.answer(f"✅ {vote_type_text}成功！", show_alert=True)

    except Exception as e:
        logger.error(f"处理投票失败 (voter: {voter_user_id}, target: {target_user_id}, tag: {tag_name}): {e}")
        await query.answer("❌ 操作失败，发生数据库错误。", show_alert=True)

    # 投票后刷新声誉卡片
    await back_to_rep_card(update, context, target_user_id)

async def back_to_rep_card(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int):
    """回调函数，用于从其他菜单返回到声誉卡片"""
    query = update.callback_query
    await query.answer()

    card_data = await build_reputation_card_data(target_user_id)
    if not card_data:
        await query.edit_message_text("无法获取该用户的声誉信息。")
        return

    is_favorite = await db_fetch_one("SELECT 1 FROM favorites WHERE user_id = $1 AND target_user_id = $2", query.from_user.id, target_user_id)
    text, keyboard = format_reputation_card(card_data, is_favorite)
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
