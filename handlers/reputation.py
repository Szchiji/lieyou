import logging
import hashlib
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import ContextTypes
from telegram.error import Forbidden, BadRequest
from database import db_transaction
from html import escape

logger = logging.getLogger(__name__)

# (get_user_fingerprint 和 send_vote_notifications 保持不变, 但通知文本会微调)
def get_user_fingerprint(user_id: int) -> str:
    return hashlib.sha256(str(user_id).encode()).hexdigest()[:8].upper()

async def send_vote_notifications(bot: Bot, nominee_username: str, nominator_id: int, vote_type: str, tag_name: str | None):
    if vote_type != 'block': return
    nominator_fingerprint = f"用户-{get_user_fingerprint(nominator_id)}"
    tag_text = f"并标记了「{escape(tag_name)}」" if tag_name else "但未添加标签"
    alert_message = (f"⚠️ **信誉警报** ⚠️\n\n"
                     f"您收藏的用户 <code>@{escape(nominee_username)}</code>\n"
                     f"刚刚被 <code>{nominator_fingerprint}</code> **拉黑**了，{tag_text}。")
    async with db_transaction() as conn:
        favorited_by_users = await conn.fetch("SELECT user_id FROM favorites WHERE favorite_username = $1", nominee_username)
    for user in favorited_by_users:
        if user['user_id'] == nominator_id: continue
        try:
            await bot.send_message(chat_id=user['user_id'], text=alert_message, parse_mode='HTML')
            await asyncio.sleep(0.1)
        except (Forbidden, BadRequest) as e:
            logger.warning(f"无法向用户 {user['user_id']} 发送收藏夹警报: {e}")

async def get_reputation_summary(nominee_username: str, nominator_id: int):
    async with db_transaction() as conn:
        profile = await conn.fetchrow("SELECT p.recommend_count, p.block_count, f.id IS NOT NULL as is_favorite FROM reputation_profiles p LEFT JOIN favorites f ON p.username = f.favorite_username AND f.user_id = $1 WHERE p.username = $2", nominator_id, nominee_username)
        if not profile:
            await conn.execute("INSERT INTO reputation_profiles (username) VALUES ($1)", nominee_username)
            return {'recommend_count': 0, 'block_count': 0, 'is_favorite': False}
    return dict(profile)

# --- 视觉革新核心 ---
async def build_summary_view(nominee_username: str, summary: dict):
    """摘要视图 - 美学重塑版"""
    text = (
        f"╭───「 <b>信誉档案</b> 」───╮\n"
        f"│\n"
        f"│  👤 <b>对象:</b> <code>@{escape(nominee_username)}</code>\n"
        f"│\n"
        f"│  👍 <b>推荐:</b> {summary['recommend_count']} 次\n"
        f"│  👎 <b>拉黑:</b> {summary['block_count']} 次\n"
        f"│\n"
        f"╰─────────────╯"
    )
    fav_icon = "🌟" if summary['is_favorite'] else "➕"
    fav_text = "已收藏" if summary['is_favorite'] else "收藏"
    fav_callback = "query_fav_remove" if summary['is_favorite'] else "query_fav_add"
    keyboard = [
        [
            InlineKeyboardButton("👍 推荐", callback_data=f"vote_recommend_{nominee_username}"),
            InlineKeyboardButton("👎 拉黑", callback_data=f"vote_block_{nominee_username}"),
        ],
        [
            InlineKeyboardButton("📊 详细标签", callback_data=f"rep_detail_{nominee_username}"),
            InlineKeyboardButton(f"{fav_icon} {fav_text}", callback_data=f"{fav_callback}_{nominee_username}")
        ],
        [
            InlineKeyboardButton("📜 查看评价者", callback_data=f"rep_voters_menu_{nominee_username}")
        ]
    ]
    return {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}

async def build_detail_view(nominee_username: str):
    """详情视图 - 美学重塑版"""
    async with db_transaction() as conn:
        votes = await conn.fetch("SELECT t.type, t.tag_name, COUNT(v.id) as count FROM votes v JOIN tags t ON v.tag_id = t.id WHERE v.nominee_username = $1 GROUP BY t.type, t.tag_name ORDER BY t.type, count DESC", nominee_username)
    
    recommend_tags, block_tags = [], []
    for vote in votes:
        line = f"  - {escape(vote['tag_name'])} ({vote['count']}票)"
        (recommend_tags if vote['type'] == 'recommend' else block_tags).append(line)

    text_parts = [f"📊 <b>详细标签:</b> <code>@{escape(nominee_username)}</code>\n" + ("-"*20)]
    if recommend_tags:
        text_parts.append("\n👍 <b>推荐标签:</b>")
        text_parts.extend(recommend_tags)
    if block_tags:
        text_parts.append("\n👎 <b>拉黑标签:</b>")
        text_parts.extend(block_tags)
    if not recommend_tags and not block_tags:
        text_parts.append("\n此用户尚未收到任何带标签的评价。")

    text = "\n".join(text_parts)
    keyboard = [[InlineKeyboardButton("⬅️ 返回档案", callback_data=f"rep_summary_{nominee_username}")]]
    return {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}

async def build_voters_menu_view(nominee_username: str):
    """新增：评价者追溯的选择菜单"""
    text = f"📜 <b>查看评价者:</b> <code>@{escape(nominee_username)}</code>\n\n请选择您想查看的评价类型："
    keyboard = [
        [
            InlineKeyboardButton("👍 查看推荐者", callback_data=f"rep_voters_recommend_{nominee_username}"),
            InlineKeyboardButton("👎 查看拉黑者", callback_data=f"rep_voters_block_{nominee_username}")
        ],
        [
            InlineKeyboardButton("⬅️ 返回档案", callback_data=f"rep_summary_{nominee_username}")
        ]
    ]
    return {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}

async def build_voters_view(nominee_username: str, vote_type: str):
    """评价者列表视图 - 美学重塑版"""
    type_text, icon = ("推荐者", "👍") if vote_type == "recommend" else ("拉黑者", "👎")
    async with db_transaction() as conn:
        voters = await conn.fetch("SELECT DISTINCT nominator_id FROM votes WHERE nominee_username = $1 AND vote_type = $2", nominee_username, vote_type)
    
    text_parts = [f"{icon} <b>{type_text}列表:</b> <code>@{escape(nominee_username)}</code>\n" + ("-"*20)]
    if not voters:
        text_parts.append("\n暂时无人做出此类评价。")
    else:
        text_parts.append("\n为保护隐私，仅显示匿名用户指纹：")
        voter_fingerprints = [f"  - <code>用户-{get_user_fingerprint(v['nominator_id'])}</code>" for v in voters]
        text_parts.extend(voter_fingerprints)
    
    text = "\n".join(text_parts)
    keyboard = [[InlineKeyboardButton("⬅️ 返回档案", callback_data=f"rep_summary_{nominee_username}")]]
    return {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}

# (handle_nomination 和 button_handler 等核心逻辑保持不变，只需更新视图调用)
async def handle_nomination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text
    try:
        nominee_username = message_text.split('@')[1].strip().split(' ')[0]
        if not nominee_username: raise ValueError("用户名不能为空")
    except (IndexError, ValueError):
        await update.message.reply_text("查询格式不正确，请使用 `查询 @用户名`。")
        return
    nominator_id = update.effective_user.id
    async with db_transaction() as conn:
        await conn.execute("INSERT INTO users (id, username) VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET username = $2", nominator_id, update.effective_user.username)
    summary = await get_reputation_summary(nominee_username, nominator_id)
    message_content = await build_summary_view(nominee_username, summary)
    await update.message.reply_text(**message_content)

async def show_reputation_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query, nominee_username = update.callback_query, query.data.split('_')[-1]
    summary = await get_reputation_summary(nominee_username, query.from_user.id)
    message_content = await build_summary_view(nominee_username, summary)
    await query.edit_message_text(**message_content)

async def show_reputation_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query, nominee_username = update.callback_query, query.data.split('_')[-1]
    message_content = await build_detail_view(nominee_username)
    await query.edit_message_text(**message_content)

async def show_voters_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query, nominee_username = update.callback_query, query.data.split('_')[-1]
    message_content = await build_voters_menu_view(nominee_username)
    await query.edit_message_text(**message_content)

async def show_reputation_voters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query, _, vote_type, nominee_username = update.callback_query, *query.data.split('_')
    message_content = await build_voters_view(nominee_username, vote_type)
    await query.edit_message_text(**message_content)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data_parts = query.data.split('_')
    action, nominee_username = data_parts[0], data_parts[-1]
    nominator_id = query.from_user.id

    if action == "vote":
        vote_type = data_parts[1]
        async with db_transaction() as conn:
            tags = await conn.fetch("SELECT id, tag_name FROM tags WHERE type = $1 ORDER BY id", vote_type)
        
        keyboard = [[InlineKeyboardButton(tag['tag_name'], callback_data=f"tag_{tag['id']}_{nominee_username}")] for tag in tags]
        keyboard.append([InlineKeyboardButton("❌ 无标签投票", callback_data=f"tag_notag_{vote_type}_{nominee_username}")])
        keyboard.append([InlineKeyboardButton("⬅️ 取消", callback_data=f"rep_summary_{nominee_username}")])
        
        type_text = '推荐' if vote_type == 'recommend' else '拉黑'
        await query.edit_message_text(f"✍️ **正在评价:** <code>@{escape(nominee_username)}</code>\n\n请为您的 **{type_text}** 操作选择一个标签：", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

    elif action == "tag":
        tag_id_str = data_parts[1]
        async with db_transaction() as conn:
            if tag_id_str == 'notag':
                vote_type, tag_id, tag_name = data_parts[2], None, None
            else:
                tag_id = int(tag_id_str)
                tag_info = await conn.fetchrow("SELECT type, tag_name FROM tags WHERE id = $1", tag_id)
                if not tag_info:
                    await query.answer("❌ 错误：标签不存在。", show_alert=True)
                    return
                vote_type, tag_name = tag_info['type'], tag_info['tag_name']
            
            await conn.execute("INSERT INTO votes (nominator_id, nominee_username, vote_type, tag_id) VALUES ($1, $2, $3, $4)", nominator_id, nominee_username, vote_type, tag_id)
            count_col = "recommend_count" if vote_type == "recommend" else "block_count"
            await conn.execute(f"UPDATE reputation_profiles SET {count_col} = {count_col} + 1 WHERE username = $1", nominee_username)
        
        asyncio.create_task(send_vote_notifications(context.bot, nominee_username, nominator_id, vote_type, tag_name))
        
        await query.answer(f"✅ 评价成功: @{nominee_username}", show_alert=True)
        # 评价成功后，直接返回更新后的主档案卡
        summary = await get_reputation_summary(nominee_username, nominator_id)
        message_content = await build_summary_view(nominee_username, summary)
        await query.edit_message_text(**message_content)
