import logging
import hashlib
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import ContextTypes
from telegram.error import Forbidden, BadRequest
from database import db_transaction
from html import escape

logger = logging.getLogger(__name__)

def get_user_fingerprint(user_id: int) -> str:
    """为用户ID生成一个简短、稳定、匿名的指纹"""
    return hashlib.sha256(str(user_id).encode()).hexdigest()[:8].upper()

# --- “灵魂法则”最终版：只保留警报，移除荣耀通知 ---
async def send_vote_notifications(bot: Bot, nominee_username: str, nominator_id: int, vote_type: str, tag_name: str | None):
    """
    在后台异步发送通知。
    根据新的法则，此功能现在只处理“拉黑”警报。
    """
    # 如果不是“拉黑”事件，则直接终止，不执行任何操作
    if vote_type != 'block':
        return

    nominator_fingerprint = f"用户-{get_user_fingerprint(nominator_id)}"
    tag_text = f"标签为「{escape(tag_name)}」" if tag_name else "无标签"

    # 功能: “收藏夹警报” (完整保留)
    async with db_transaction() as conn:
        favorited_by_users = await conn.fetch(
            "SELECT user_id FROM favorites WHERE favorite_username = $1",
            nominee_username
        )
    
    alert_message = (
        f"⚠️ **信誉警报** ⚠️\n\n"
        f"您收藏的用户 <code>@{escape(nominee_username)}</code> 刚刚收到了一个来自 <code>{nominator_fingerprint}</code> 的 **拉黑** 评价，{tag_text}。"
    )
    for user in favorited_by_users:
        if user['user_id'] == nominator_id:
            continue
        try:
            await bot.send_message(chat_id=user['user_id'], text=alert_message, parse_mode='HTML')
            await asyncio.sleep(0.1)
        except (Forbidden, BadRequest) as e:
            logger.warning(f"无法向用户 {user['user_id']} 发送收藏夹警报: {e}")


# --- 以下为既有代码，无需改动 ---

async def get_reputation_summary(nominee_username: str, nominator_id: int):
    async with db_transaction() as conn:
        profile = await conn.fetchrow(
            """
            SELECT p.recommend_count, p.block_count, f.id IS NOT NULL as is_favorite
            FROM reputation_profiles p
            LEFT JOIN favorites f ON p.username = f.favorite_username AND f.user_id = $1
            WHERE p.username = $2
            """, nominator_id, nominee_username
        )
        if not profile:
            await conn.execute("INSERT INTO reputation_profiles (username) VALUES ($1)", nominee_username)
            return {'recommend_count': 0, 'block_count': 0, 'is_favorite': False}
    return dict(profile)

async def build_summary_view(nominee_username: str, summary: dict):
    text = (f"<b>信誉档案: @{escape(nominee_username)}</b>\n\n"
            f"👍 推荐: {summary['recommend_count']}\n"
            f"👎 拉黑: {summary['block_count']}")
    fav_button_text = "⭐ 已收藏" if summary['is_favorite'] else "➕ 加入收藏"
    fav_button_callback = "query_fav_remove" if summary['is_favorite'] else "query_fav_add"
    keyboard = [
        [InlineKeyboardButton("👍 评价", callback_data=f"vote_recommend_{nominee_username}"),
         InlineKeyboardButton("👎 评价", callback_data=f"vote_block_{nominee_username}"),
         InlineKeyboardButton(fav_button_text, callback_data=f"{fav_button_callback}_{nominee_username}")],
        [InlineKeyboardButton("📊 查看详情", callback_data=f"rep_detail_{nominee_username}")],
        [InlineKeyboardButton("👍 谁推荐了?", callback_data=f"rep_voters_recommend_{nominee_username}"),
         InlineKeyboardButton("👎 谁拉黑了?", callback_data=f"rep_voters_block_{nominee_username}")]
    ]
    return {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}

async def build_detail_view(nominee_username: str):
    async with db_transaction() as conn:
        votes = await conn.fetch("SELECT t.type, t.tag_name, COUNT(v.id) as count FROM votes v JOIN tags t ON v.tag_id = t.id WHERE v.nominee_username = $1 GROUP BY t.type, t.tag_name ORDER BY t.type, count DESC", nominee_username)
    recommend_tags, block_tags, total_recommends, total_blocks = [], [], 0, 0
    for vote in votes:
        line = f"- {escape(vote['tag_name'])}: {vote['count']}"
        (recommend_tags if vote['type'] == 'recommend' else block_tags).append(line)
        if vote['type'] == 'recommend': total_recommends += vote['count']
        else: total_blocks += vote['count']
    text_parts = [f"<b>信誉详情: @{escape(nominee_username)}</b>\n"]
    if recommend_tags: text_parts.extend([f"<b>👍 推荐 (总计: {total_recommends}):</b>", *recommend_tags])
    if block_tags: text_parts.extend([f"\n<b>👎 拉黑 (总计: {total_blocks}):</b>", *block_tags])
    if not recommend_tags and not block_tags: text_parts.append("\n此用户尚未收到任何带标签的评价。")
    text = "\n".join(text_parts)
    keyboard = [[InlineKeyboardButton("⬅️ 返回摘要", callback_data=f"rep_summary_{nominee_username}")]]
    return {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}

async def build_voters_view(nominee_username: str, vote_type: str):
    type_text = "推荐者" if vote_type == "recommend" else "拉黑者"
    icon = "👍" if vote_type == "recommend" else "👎"
    async with db_transaction() as conn:
        voters = await conn.fetch("SELECT DISTINCT nominator_id FROM votes WHERE nominee_username = $1 AND vote_type = $2", nominee_username, vote_type)
    text_parts = [f"<b>{icon} {type_text}列表: @{escape(nominee_username)}</b>\n"]
    if not voters: text_parts.append("\n暂时无人做出此类评价。")
    else:
        text_parts.append("为保护隐私，仅显示匿名用户指纹：")
        text_parts.extend([f"- <code>用户-{get_user_fingerprint(v['nominator_id'])}</code>" for v in voters])
    text = "\n".join(text_parts)
    keyboard = [[InlineKeyboardButton("⬅️ 返回摘要", callback_data=f"rep_summary_{nominee_username}")]]
    return {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}

async def handle_nomination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text
    try:
        nominee_username = message_text.split('@')[1].strip().split(' ')[0]
        if not nominee_username: raise ValueError("用户名不能为空")
    except (IndexError, ValueError) as e:
        await update.message.reply_text("查询格式不正确，请使用 `查询 @用户名`。")
        return
    nominator_id = update.effective_user.id
    async with db_transaction() as conn:
        await conn.execute("INSERT INTO users (id, username) VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET username = $2", nominator_id, update.effective_user.username)
    summary = await get_reputation_summary(nominee_username, nominator_id)
    message_content = await build_summary_view(nominee_username, summary)
    await update.message.reply_text(**message_content)

async def show_reputation_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    nominee_username = query.data.split('_')[-1]
    nominator_id = query.from_user.id
    summary = await get_reputation_summary(nominee_username, nominator_id)
    message_content = await build_summary_view(nominee_username, summary)
    await query.edit_message_text(**message_content)

async def show_reputation_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    nominee_username = query.data.split('_')[-1]
    message_content = await build_detail_view(nominee_username)
    await query.edit_message_text(**message_content)

async def show_reputation_voters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, _, vote_type, nominee_username = query.data.split('_')
    message_content = await build_voters_view(nominee_username, vote_type)
    await query.edit_message_text(**message_content)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data_parts = query.data.split('_')
    action = data_parts[0]
    
    if action == "vote":
        nominee_username = query.data.split('_', 2)[-1]
        context.user_data['current_nominee'] = nominee_username
    else:
        nominee_username = context.user_data.get('current_nominee')
    if not nominee_username:
        await query.answer("抱歉，上下文信息已丢失，请重新发起查询。", show_alert=True)
        return

    nominator_id = query.from_user.id
    
    if action == "vote":
        vote_type = data_parts[1]
        async with db_transaction() as conn:
            tags = await conn.fetch("SELECT id, tag_name FROM tags WHERE type = $1 ORDER BY id", vote_type)
        keyboard = [[InlineKeyboardButton(tag['tag_name'], callback_data=f"tag_{tag['id']}")] for tag in tags]
        keyboard.append([InlineKeyboardButton("❌ 无标签投票", callback_data=f"tag_notag_{vote_type}")])
        keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data=f"rep_summary_{nominee_username}")])
        type_text = '推荐' if vote_type == 'recommend' else '拉黑'
        await query.edit_message_text(f"请为您的 **{type_text}** 选择一个标签：", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif action == "tag":
        tag_id_str, tag_name = data_parts[1], None
        async with db_transaction() as conn:
            if tag_id_str == 'notag':
                vote_type, tag_id = data_parts[2], None
            else:
                tag_id = int(tag_id_str)
                tag_info = await conn.fetchrow("SELECT type, tag_name FROM tags WHERE id = $1", tag_id)
                if not tag_info:
                    await query.answer("错误：标签不存在。", show_alert=True)
                    return
                vote_type, tag_name = tag_info['type'], tag_info['tag_name']
            
            await conn.execute("INSERT INTO votes (nominator_id, nominee_username, vote_type, tag_id) VALUES ($1, $2, $3, $4)", nominator_id, nominee_username, vote_type, tag_id)
            count_col = "recommend_count" if vote_type == "recommend" else "block_count"
            await conn.execute(f"UPDATE reputation_profiles SET {count_col} = {count_col} + 1 WHERE username = $1", nominee_username)
        
        asyncio.create_task(send_vote_notifications(context.bot, nominee_username, nominator_id, vote_type, tag_name))
        
        await query.answer(f"✅ 您已成功评价 @{nominee_username}！", show_alert=True)
        summary = await get_reputation_summary(nominee_username, nominator_id)
        message_content = await build_summary_view(nominee_username, summary)
        await query.edit_message_text(**message_content)
