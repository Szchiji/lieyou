import logging
import hashlib
import asyncio
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import ContextTypes
from telegram.error import Forbidden, BadRequest
from database import db_transaction, update_user_activity
from html import escape

logger = logging.getLogger(__name__)

def get_user_fingerprint(user_id: int) -> str:
    return hashlib.sha256(str(user_id).encode()).hexdigest()[:8].upper()

async def send_vote_notifications(bot: Bot, nominee_username: str, nominator_id: int, vote_type: str, tag_name: str | None):
    if vote_type != 'block': return
    nominator_fingerprint = f"求道者-{get_user_fingerprint(nominator_id)}"
    tag_text = f"并留下了箴言：『{escape(tag_name)}』" if tag_name else "但未留下箴言"
    alert_message = (f"⚠️ **命运警示** ⚠️\n\n"
                     f"您星盘中的存在 <code>@{escape(nominee_username)}</code>\n"
                     f"刚刚被 <code>{nominator_fingerprint}</code> **降下警示**，{tag_text}。")
    async with db_transaction() as conn:
        favorited_by_users = await conn.fetch("SELECT user_id FROM favorites WHERE favorite_username = $1", nominee_username)
    for user in favorited_by_users:
        if user['user_id'] == nominator_id: continue
        try:
            await bot.send_message(chat_id=user['user_id'], text=alert_message, parse_mode='HTML')
            await asyncio.sleep(0.1)
        except (Forbidden, BadRequest) as e:
            logger.warning(f"无法向用户 {user['user_id']} 发送星盘警示: {e}")

async def get_reputation_summary(nominee_username: str, nominator_id: int):
    async with db_transaction() as conn:
        profile = await conn.fetchrow("""
            SELECT p.recommend_count, p.block_count, f.id IS NOT NULL as is_favorite 
            FROM reputation_profiles p 
            LEFT JOIN favorites f ON p.username = f.favorite_username AND f.user_id = $1 
            WHERE p.username = $2
        """, nominator_id, nominee_username)
        if not profile:
            await conn.execute("""
                INSERT INTO reputation_profiles (username) 
                VALUES ($1)
            """, nominee_username)
            return {'recommend_count': 0, 'block_count': 0, 'is_favorite': False}
    return dict(profile)

async def build_summary_view(nominee_username: str, summary: dict):
    # 计算声誉评分(范围-10到10)
    total_votes = summary['recommend_count'] + summary['block_count']
    if total_votes == 0:
        reputation_score = 0
    else:
        reputation_score = round((summary['recommend_count'] - summary['block_count']) / total_votes * 10, 1)
    
    # 确定声誉级别和对应图标
    if reputation_score >= 7:
        rep_icon = "🌟"
        rep_level = "崇高"
    elif reputation_score >= 3:
        rep_icon = "✨"
        rep_level = "良好"
    elif reputation_score >= -3:
        rep_icon = "⚖️"
        rep_level = "中立"
    elif reputation_score >= -7:
        rep_icon = "⚠️"
        rep_level = "警惕"
    else:
        rep_icon = "☠️"
        rep_level = "危险"
    
    text = (
        f"╭───「 📜 <b>神谕之卷</b> 」───╮\n"
        f"│\n"
        f"│  👤 <b>求问对象:</b> <code>@{escape(nominee_username)}</code>\n"
        f"│\n"
        f"│  👍 <b>赞誉:</b> {summary['recommend_count']} 次\n"
        f"│  👎 <b>警示:</b> {summary['block_count']} 次\n"
        f"│  {rep_icon} <b>神谕判定:</b> {rep_level} ({reputation_score})\n"
        f"│\n"
        f"╰──────────────╯"
    )
    fav_icon = "🌟" if summary['is_favorite'] else "➕"
    fav_text = "移出星盘" if summary['is_favorite'] else "加入星盘"
    fav_callback = "query_fav_remove" if summary['is_favorite'] else "query_fav_add"
    keyboard = [
        [
            InlineKeyboardButton("👍 献上赞誉", callback_data=f"vote_recommend_{nominee_username}"),
            InlineKeyboardButton("👎 降下警示", callback_data=f"vote_block_{nominee_username}"),
        ],
        [
            InlineKeyboardButton("📜 查看箴言", callback_data=f"rep_detail_{nominee_username}"),
            InlineKeyboardButton(f"{fav_icon} {fav_text}", callback_data=f"{fav_callback}_{nominee_username}")
        ],
        [
            InlineKeyboardButton("⚖️ 追溯献祭者", callback_data=f"rep_voters_menu_{nominee_username}")
        ]
    ]
    return {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}

async def handle_username_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理直接查询用户名的命令（群聊和私聊均可使用）"""
    message = update.message
    
    # 通过正则表达式提取用户名
    match = re.match(r'^查询\s+@(\w{5,})$', message.text)
    if match:
        nominee_username = match.group(1)
        nominator_id = update.effective_user.id
        nominator_username = update.effective_user.username
        
        # 更新用户活动记录
        await update_user_activity(nominator_id, nominator_username)
        
        # 获取声誉摘要
        summary = await get_reputation_summary(nominee_username, nominator_id)
        message_content = await build_summary_view(nominee_username, summary)
        await update.message.reply_text(**message_content)

async def handle_nomination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理在群聊中@用户的情况"""
    message = update.message
    nominee_username = None
    if context.matches:
        match = context.matches[0]
        nominee_username = match.group(1) or match.group(2)
    if not nominee_username:
        return
    
    nominator_id = update.effective_user.id
    nominator_username = update.effective_user.username
    
    # 更新用户活动记录
    await update_user_activity(nominator_id, nominator_username)
    
    # 获取并显示声誉摘要
    summary = await get_reputation_summary(nominee_username, nominator_id)
    message_content = await build_summary_view(nominee_username, summary)
    await update.message.reply_text(**message_content)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data_parts = query.data.split('_')
    action, nominee_username = data_parts[0], data_parts[-1]
    nominator_id = query.from_user.id
    nominator_username = query.from_user.username
    
    # 更新用户活动
    await update_user_activity(nominator_id, nominator_username)

    if action == "vote":
        vote_type = data_parts[1]
        async with db_transaction() as conn:
            # 检查用户是否已经对该用户进行过此类型的评价
            existing_vote = await conn.fetchrow("""
                SELECT id FROM votes 
                WHERE nominator_id = $1 AND nominee_username = $2 AND vote_type = $3
                AND created_at > NOW() - INTERVAL '24 hours'
            """, nominator_id, nominee_username, vote_type)
            
            if existing_vote:
                await query.answer("⚠️ 你已在24小时内对此存在做出过相同判断。", show_alert=True)
                return
            
            # 获取标签列表
            tags = await conn.fetch("SELECT id, tag_name FROM tags WHERE type = $1 ORDER BY tag_name", vote_type)
        
        keyboard = [[InlineKeyboardButton(f"『{escape(tag['tag_name'])}』", callback_data=f"tag_{tag['id']}_{nominee_username}")] for tag in tags]
        keyboard.append([InlineKeyboardButton("❌ 仅判断，不留箴言", callback_data=f"tag_notag_{vote_type}_{nominee_username}")])
        keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data=f"rep_summary_{nominee_username}")])
        
        type_text = '赞誉' if vote_type == 'recommend' else '警示'
        await query.edit_message_text(f"✍️ **正在审判:** <code>@{escape(nominee_username)}</code>\n\n请为您的 **{type_text}** 选择一句箴言：", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

    elif action == "tag":
        tag_id_str = data_parts[1]
        async with db_transaction() as conn:
            if tag_id_str == 'notag':
                vote_type, tag_id, tag_name = data_parts[2], None, None
            else:
                tag_id = int(tag_id_str)
                tag_info = await conn.fetchrow("SELECT type, tag_name FROM tags WHERE id = $1", tag_id)
                if not tag_info:
                    await query.answer("❌ 错误：此箴言已不存在。", show_alert=True)
                    return
                vote_type, tag_name = tag_info['type'], tag_info['tag_name']
            
            # 检查24小时内是否已评价
            existing_vote = await conn.fetchrow("""
                SELECT id FROM votes 
                WHERE nominator_id = $1 AND nominee_username = $2 AND vote_type = $3
                AND created_at > NOW() - INTERVAL '24 hours'
            """, nominator_id, nominee_username, vote_type)
            
            if existing_vote:
                await query.answer("⚠️ 你已在24小时内对此存在做出过相同判断。", show_alert=True)
                return
            
            # 添加投票
            await conn.execute("""
                INSERT INTO votes (nominator_id, nominee_username, vote_type, tag_id) 
                VALUES ($1, $2, $3, $4)
            """, nominator_id, nominee_username, vote_type, tag_id)
            
            # 更新声誉档案
            count_col = "recommend_count" if vote_type == "recommend" else "block_count"
            await conn.execute(f"""
                INSERT INTO reputation_profiles (username, {count_col}, last_updated) 
                VALUES ($1, 1, CURRENT_TIMESTAMP)
                ON CONFLICT (username) DO UPDATE 
                SET {count_col} = reputation_profiles.{count_col} + 1,
                    last_updated = CURRENT_TIMESTAMP
            """, nominee_username)
        
        # 发送警示通知
        asyncio.create_task(send_vote_notifications(context.bot, nominee_username, nominator_id, vote_type, tag_name))
        
        # 更新界面
        await query.answer(f"✅ 你的判断已载入史册: @{nominee_username}", show_alert=True)
        summary = await get_reputation_summary(nominee_username, nominator_id)
        message_content = await build_summary_view(nominee_username, summary)
        await query.edit_message_text(**message_content)

async def show_reputation_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    nominee_username = query.data.split('_')[-1]
    nominator_id = query.from_user.id
    
    # 更新用户活动
    await update_user_activity(nominator_id, query.from_user.username)
    
    # 获取并显示声誉摘要
    summary = await get_reputation_summary(nominee_username, nominator_id)
    message_content = await build_summary_view(nominee_username, summary)
    await query.edit_message_text(**message_content)

async def build_detail_view(nominee_username: str):
    async with db_transaction() as conn:
        # 获取按标签分组的投票
        votes = await conn.fetch("""
            SELECT t.type, t.tag_name, COUNT(v.id) as count 
            FROM votes v 
            JOIN tags t ON v.tag_id = t.id 
            WHERE v.nominee_username = $1 
            GROUP BY t.type, t.tag_name 
            ORDER BY t.type, count DESC
        """, nominee_username)
        
        # 获取无标签投票数
        no_tag_votes = await conn.fetch("""
            SELECT vote_type, COUNT(*) as count
            FROM votes
            WHERE nominee_username = $1 AND tag_id IS NULL
            GROUP BY vote_type
        """, nominee_username)
    
    recommend_tags, block_tags = [], []
    
    # 处理有标签的投票
    for vote in votes:
        line = f"  - 『{escape(vote['tag_name'])}』 ({vote['count']}次)"
        (recommend_tags if vote['type'] == 'recommend' else block_tags).append(line)
    
    # 处理无标签的投票
    for vote in no_tag_votes:
        count = vote['count']
        if vote['vote_type'] == 'recommend':
            recommend_tags.append(f"  - 『无箴言』 ({count}次)")
        else:
            block_tags.append(f"  - 『无箴言』 ({count}次)")

    text_parts = [f"📜 <b>箴言详情:</b> <code>@{escape(nominee_username)}</code>\n" + ("-"*20)]
    if recommend_tags:
        text_parts.append("\n👍 <b>赞誉类箴言:</b>")
        text_parts.extend(recommend_tags)
    if block_tags:
        text_parts.append("\n👎 <b>警示类箴言:</b>")
        text_parts.extend(block_tags)
    if not recommend_tags and not block_tags:
        text_parts.append("\n此存在尚未被赋予任何箴言。")

    text = "\n".join(text_parts)
    keyboard = [[InlineKeyboardButton("⬅️ 返回卷宗", callback_data=f"rep_summary_{nominee_username}")]]
    return {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}

async def show_reputation_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    nominee_username = query.data.split('_')[-1]
    
    # 更新用户活动
    await update_user_activity(query.from_user.id, query.from_user.username)
    
    # 显示声誉详情
    message_content = await build_detail_view(nominee_username)
    await query.edit_message_text(**message_content)
    
async def build_voters_menu_view(nominee_username: str):
    text = f"⚖️ <b>追溯献祭者:</b> <code>@{escape(nominee_username)}</code>\n\n请选择您想追溯的审判类型："
    keyboard = [
        [
            InlineKeyboardButton("👍 查看赞誉者", callback_data=f"rep_voters_recommend_{nominee_username}"),
            InlineKeyboardButton("👎 查看警示者", callback_data=f"rep_voters_block_{nominee_username}")
        ],
        [
            InlineKeyboardButton("⬅️ 返回卷宗", callback_data=f"rep_summary_{nominee_username}")
        ]
    ]
    return {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}

async def show_voters_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    nominee_username = query.data.split('_')[-1]
    
    # 更新用户活动
    await update_user_activity(query.from_user.id, query.from_user.username)
    
    message_content = await build_voters_menu_view(nominee_username)
    await query.edit_message_text(**message_content)

async def build_voters_view(nominee_username: str, vote_type: str):
    type_text, icon = ("赞誉者", "👍") if vote_type == "recommend" else ("警示者", "👎")
    async with db_transaction() as conn:
        # 获取投票者列表以及他们的投票时间
        voters = await conn.fetch("""
            SELECT DISTINCT nominator_id, MAX(created_at) as last_vote
            FROM votes 
            WHERE nominee_username = $1 AND vote_type = $2
            GROUP BY nominator_id
            ORDER BY last_vote DESC
        """, nominee_username, vote_type)
    
    text_parts = [f"{icon} <b>{type_text}列表:</b> <code>@{escape(nominee_username)}</code>\n" + ("-"*20)]
    if not voters:
        text_parts.append("\n暂时无人做出此类审判。")
    else:
        text_parts.append("\n为守护天机，仅展示匿名身份印记：")
        for voter in voters:
            last_vote_time = voter['last_vote'].strftime("%Y-%m-%d")
            fingerprint = get_user_fingerprint(voter['nominator_id'])
            text_parts.append(f"  - <code>求道者-{fingerprint}</code> ({last_vote_time})")
    
    text = "\n".join(text_parts)
    keyboard = [[InlineKeyboardButton("⬅️ 返回卷宗", callback_data=f"rep_summary_{nominee_username}")]]
    return {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}

async def show_reputation_voters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, _, vote_type, nominee_username = query.data.split('_')
    
    # 更新用户活动
    await update_user_activity(query.from_user.id, query.from_user.username)
    
    message_content = await build_voters_view(nominee_username, vote_type)
    await query.edit_message_text(**message_content)
