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
    
    # 使用更美观的格式，减少可复制性
    text = (
        f"┏━━━━「 📜 <b>神谕之卷</b> 」━━━━┓\n"
        f"┃                          ┃\n"
        f"┃  👤 <b>求问对象:</b> @{escape(nominee_username)}   ┃\n"
        f"┃                          ┃\n"
        f"┃  👍 <b>赞誉:</b> {summary['recommend_count']} 次        ┃\n"
        f"┃  👎 <b>警示:</b> {summary['block_count']} 次        ┃\n"
        f"┃  {rep_icon} <b>神谕判定:</b> {rep_level} ({reputation_score})  ┃\n"
        f"┃                          ┃\n"
        f"┗━━━━━━━━━━━━━━━━━━┛"
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
    
    # 修改正则表达式，确保可以匹配包含下划线的用户名
    match = re.match(r'^查询\s+@(\w+)$', message.text)
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
    
    # 修改以更好地处理带下划线的用户名
    if update.message.text:
        # 直接匹配@后面的所有单词字符（包括下划线）
        matches = re.findall(r'@(\w+)', update.message.text)
        if matches:
            nominee_username = matches[0]
    
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
    data = query.data
    
    # 更精确的解析方法
    if data.startswith('vote_'):
        # vote_recommend_username 或 vote_block_username
        action = 'vote'
        parts = data.split('_', 2)  # 只分割前两个下划线
        if len(parts) == 3:
            vote_type = parts[1]
            nominee_username = parts[2]  # 保留完整用户名，包括可能的下划线
        else:
            await query.answer("❌ 数据格式错误", show_alert=True)
            return
    elif data.startswith('tag_'):
        # tag_id_username 或 tag_notag_type_username
        action = 'tag'
        if data.startswith('tag_notag_'):
            # 特殊处理无标签情况
            parts = data.split('_', 3)  # tag_notag_type_username
            if len(parts) == 4:
                tag_id_str = 'notag'
                vote_type = parts[2]
                nominee_username = parts[3]
            else:
                await query.answer("❌ 数据格式错误", show_alert=True)
                return
        else:
            # 正常标签情况
            parts = data.split('_', 2)  # tag_id_username
            if len(parts) == 3:
                tag_id_str = parts[1]
                nominee_username = parts[2]
            else:
                await query.answer("❌ 数据格式错误", show_alert=True)
                return
    else:
        # 不是我们关心的回调数据
        return
        
    nominator_id = query.from_user.id
    nominator_username = query.from_user.username
    
    # 更新用户活动
    await update_user_activity(nominator_id, nominator_username)

    if action == "vote":
        async with db_transaction() as conn:
            # 检查votes表是否有所需字段
            columns = await conn.fetch("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'votes' AND column_name IN ('vote_type', 'created_at')
            """)
            column_names = [col['column_name'] for col in columns]
            
            # 如果缺少字段，尝试添加
            if 'vote_type' not in column_names:
                try:
                    await conn.execute("ALTER TABLE votes ADD COLUMN vote_type TEXT NOT NULL DEFAULT 'recommend';")
                    logger.info("✅ 添加了'vote_type'列到votes表")
                except Exception as e:
                    logger.error(f"添加'vote_type'列失败: {e}")
                    await query.answer("❌ 系统错误，请联系管理员", show_alert=True)
                    return
                
            if 'created_at' not in column_names:
                try:
                    await conn.execute("ALTER TABLE votes ADD COLUMN created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;")
                    logger.info("✅ 添加了'created_at'列到votes表")
                except Exception as e:
                    logger.error(f"添加'created_at'列失败: {e}")
                    await query.answer("❌ 系统错误，请联系管理员", show_alert=True)
                    return
                    
            # 现在检查用户是否已经对该用户进行过此类型的评价
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
        await query.edit_message_text(f"✍️ <b>正在审判:</b> <code>@{escape(nominee_username)}</code>\n\n请为您的 <b>{type_text}</b> 选择一句箴言：", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

    elif action == "tag":
        # 确认votes表有必要的列
        async with db_transaction() as conn:
            # 检查并添加缺失的列
            columns = await conn.fetch("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'votes' AND column_name IN ('vote_type', 'created_at')
            """)
            column_names = [col['column_name'] for col in columns]
            
            if 'vote_type' not in column_names:
                await conn.execute("ALTER TABLE votes ADD COLUMN vote_type TEXT NOT NULL DEFAULT 'recommend';")
                logger.info("✅ 添加了'vote_type'列到votes表")
                
            if 'created_at' not in column_names:
                await conn.execute("ALTER TABLE votes ADD COLUMN created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;")
                logger.info("✅ 添加了'created_at'列到votes表")
            
            # 检查tag_id是否允许为null
            tag_id_nullable = False
            try:
                constraints = await conn.fetch("""
                    SELECT is_nullable 
                    FROM information_schema.columns 
                    WHERE table_name = 'votes' AND column_name = 'tag_id'
                """)
                tag_id_nullable = constraints and constraints[0]['is_nullable'] == 'YES'
                
                if not tag_id_nullable:
                    # 修改表允许tag_id为NULL
                    await conn.execute("ALTER TABLE votes ALTER COLUMN tag_id DROP NOT NULL;")
                    logger.info("✅ 修改了votes表的tag_id列允许NULL值")
                    tag_id_nullable = True
            except Exception as e:
                logger.error(f"检查或修改tag_id约束失败: {e}")
                
            # 继续处理标签
            if tag_id_str == 'notag':
                vote_type = parts[2]
                tag_id, tag_name = None, None
            else:
                try:
                    tag_id = int(tag_id_str)
                    tag_info = await conn.fetchrow("SELECT type, tag_name FROM tags WHERE id = $1", tag_id)
                    if not tag_info:
                        await query.answer("❌ 错误：此箴言已不存在。", show_alert=True)
                        return
                    vote_type, tag_name = tag_info['type'], tag_info['tag_name']
                except ValueError:
                    await query.answer("❌ 错误：标签ID无效", show_alert=True)
                    return
            
            try:
                # 添加投票 - 使用安全的SQL语句
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
            except Exception as e:
                logger.error(f"投票操作失败: {e}")
                await query.answer("❌ 操作失败，可能数据库结构需要更新", show_alert=True)
                return
        
        # 发送警示通知
        asyncio.create_task(send_vote_notifications(context.bot, nominee_username, nominator_id, vote_type, tag_name))
        
        # 更新界面
        await query.answer(f"✅ 你的判断已载入史册: @{nominee_username}", show_alert=True)
        summary = await get_reputation_summary(nominee_username, nominator_id)
        message_content = await build_summary_view(nominee_username, summary)
        await query.edit_message_text(**message_content)

async def show_reputation_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # 确保正确提取用户名（使用_join而不是简单的split）
    parts = query.data.split('_')
    action = parts[0] + '_' + parts[1]  # rep_summary
    # 将剩余部分作为用户名（可能包含下划线）
    nominee_username = '_'.join(parts[2:]) if len(parts) > 2 else ''
    
    nominator_id = query.from_user.id
    
    # 更新用户活动
    await update_user_activity(nominator_id, query.from_user.username)
    
    # 获取并显示声誉摘要
    summary = await get_reputation_summary(nominee_username, nominator_id)
    message_content = await build_summary_view(nominee_username, summary)
    await query.edit_message_text(**message_content)

async def build_detail_view(nominee_username: str):
    async with db_transaction() as conn:
        # 检查votes表是否有vote_type列
        columns = await conn.fetch("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'votes' AND column_name = 'vote_type'
        """)
        has_vote_type = len(columns) > 0
        
        if not has_vote_type:
            # 如果没有vote_type列，返回一个简化的视图
            text = f"📜 <b>箴言详情:</b> <code>@{escape(nominee_username)}</code>\n\n" + \
                   "⚠️ 系统正在维护中，暂时无法查看详情。请稍后再试。"
            keyboard = [[InlineKeyboardButton("⬅️ 返回卷宗", callback_data=f"rep_summary_{nominee_username}")]]
            return {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}
        
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

    # 使用更美观的格式显示箴言详情
    text_parts = [f"📜 <b>箴言详情:</b> <code>@{escape(nominee_username)}</code>\n" + ("━"*30)]
    
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
    # 正确解析回调数据，保留完整用户名
    parts = query.data.split('_')
    action = parts[0] + '_' + parts[1]  # rep_detail
    nominee_username = '_'.join(parts[2:])  # 将剩余部分作为用户名
    
    # 更新用户活动
    await update_user_activity(query.from_user.id, query.from_user.username)
    
    # 显示声誉详情
    message_content = await build_detail_view(nominee_username)
    await query.edit_message_text(**message_content)
    
async def build_voters_menu_view(nominee_username: str):
    # 更美观的追溯献祭者菜单
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
    # 正确解析回调数据，保留完整用户名
    parts = query.data.split('_')
    action = parts[0] + '_' + parts[1] + '_' + parts[2]  # rep_voters_menu
    nominee_username = '_'.join(parts[3:])  # 将剩余部分作为用户名
    
    # 更新用户活动
    await update_user_activity(query.from_user.id, query.from_user.username)
    
    message_content = await build_voters_menu_view(nominee_username)
    await query.edit_message_text(**message_content)

async def build_voters_view(nominee_username: str, vote_type: str):
    type_text, icon = ("赞誉者", "👍") if vote_type == "recommend" else ("警示者", "👎")
    
    # 检查votes表结构
    async with db_transaction() as conn:
        columns = await conn.fetch("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'votes' AND column_name IN ('vote_type', 'created_at')
        """)
        column_names = [col['column_name'] for col in columns]
        
        has_vote_type = 'vote_type' in column_names
        has_created_at = 'created_at' in column_names
        
        if not has_vote_type or not has_created_at:
            # 如果缺少必要的列，显示错误消息
            text = f"{icon} <b>{type_text}列表:</b> <code>@{escape(nominee_username)}</code>\n\n" + \
                   "⚠️ 系统正在维护中，暂时无法查看献祭者。请稍后再试。"
            keyboard = [[InlineKeyboardButton("⬅️ 返回卷宗", callback_data=f"rep_summary_{nominee_username}")]]
            return {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}
        
        # 获取投票者列表
        voters = await conn.fetch("""
            SELECT DISTINCT nominator_id, MAX(created_at) as last_vote
            FROM votes 
            WHERE nominee_username = $1 AND vote_type = $2
            GROUP BY nominator_id
            ORDER BY last_vote DESC
        """, nominee_username, vote_type)
    
    # 使用更美观的格式显示投票者列表
    text_parts = [f"{icon} <b>{type_text}列表:</b> <code>@{escape(nominee_username)}</code>\n" + ("━"*30)]
    
    if not voters:
        text_parts.append("\n暂时无人做出此类审判。")
    else:
        text_parts.append("\n为守护天机，仅展示匿名身份印记：")
        for voter in voters:
            last_vote_time = voter['last_vote'].strftime("%Y-%m-%d")
            fingerprint = get_user_fingerprint(voter['nominator_id'])
            text_parts.append(f"  - <code>求道者-{fingerprint}</code> ({last_vote_time})")
    
    text = "\n".join(text_parts)
    # 确保返回按钮带着正确的用户名上下文
    keyboard = [[InlineKeyboardButton("⬅️ 返回卷宗", callback_data=f"rep_summary_{nominee_username}")]]
    return {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}

async def show_reputation_voters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # 正确解析回调数据，保留完整用户名
    parts = query.data.split('_')
    # rep_voters_recommend_username 或 rep_voters_block_username
    if len(parts) >= 4:
        action = parts[0] + '_' + parts[1]  # rep_voters
        vote_type = parts[2]  # recommend 或 block
        nominee_username = '_'.join(parts[3:])  # 将剩余部分作为用户名
        
        # 更新用户活动
        await update_user_activity(query.from_user.id, query.from_user.username)
        
        message_content = await build_voters_view(nominee_username, vote_type)
        await query.edit_message_text(**message_content)
    else:
        await query.answer("❌ 错误：无法解析用户信息", show_alert=True)
