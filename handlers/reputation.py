from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User, MessageEntity
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown
from database import db_cursor
import logging

logger = logging.getLogger(__name__)

async def register_user_if_not_exists(user: User):
    if not user or user.is_bot: return
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO users (id, username, first_name) VALUES (%s, %s, %s) ON CONFLICT (id) DO UPDATE SET username = EXCLUDED.username, first_name = EXCLUDED.first_name;",
            (user.id, user.username, user.first_name)
        )

# --- 最终的、简化的处理器 ---
async def handle_nomination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    统一处理 '查询 @username' 格式的请求。
    """
    message = update.effective_message
    reporter = update.effective_user
    await register_user_if_not_exists(reporter)

    target_username = None
    for entity, text in message.parse_entities([MessageEntity.MENTION]).items():
        if entity.type == MessageEntity.MENTION:
            target_username = text[1:] # 去掉@
            break
    
    if not target_username:
        # 此情况在正常过滤器下不应发生，作为安全措施
        await message.reply_text("请提供一个 @username。用法: `查询 @username`", parse_mode='MarkdownV2')
        return

    with db_cursor() as cur:
        cur.execute("SELECT * FROM users WHERE username = %s", (target_username,))
        target_user_data = cur.fetchone()

    if not target_user_data:
        safe_username = escape_markdown(target_username, version=2)
        await message.reply_text(
            f"❌ 我还不认识 *@{safe_username}*。\n请先让他/她与我私聊一次，我才能认识他/她。",
            parse_mode='MarkdownV2'
        )
        return

    # 从数据库信息构建一个 User 对象
    target_user = User(
        id=target_user_data['id'],
        first_name=target_user_data['first_name'],
        is_bot=False,
        username=target_user_data['username']
    )

    if reporter.id == target_user.id:
        await message.reply_text("你不能查询自己！")
        return
        
    await _proceed_with_nomination(message, reporter, target_user)


async def _proceed_with_nomination(message, reporter, target_user):
    """核心逻辑：创建包含标签的信誉面板。"""
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO targets (id, username, first_name, first_reporter_id) VALUES (%s, %s, %s, %s) ON CONFLICT(id) DO NOTHING",
            (target_user.id, target_user.username, target_user.first_name, reporter.id)
        )
        cur.execute("SELECT upvotes, downvotes FROM targets WHERE id = %s", (target_user.id,))
        target_data = cur.fetchone()
        cur.execute("""
            SELECT t.tag_text, COUNT(at.tag_id) as tag_count
            FROM applied_tags at JOIN tags t ON at.tag_id = t.id
            WHERE at.vote_target_id = %s GROUP BY t.tag_text
            ORDER BY tag_count DESC LIMIT 5
        """, (target_user.id,))
        top_tags = cur.fetchall()

    keyboard = await build_vote_keyboard(target_user.id)
    safe_first_name = escape_markdown(target_user.first_name, version=2)
    safe_username = escape_markdown(target_user.username or 'N/A', version=2)

    text = (
        f"👤 *用户信誉档案: {safe_first_name} \(@{safe_username}\)*\n"
        f"当前状态: \[👍{target_data['upvotes']}\] \[👎{target_data['downvotes']}\]\n\n"
    )
    if top_tags:
        text += "*热门标签:*\n"
        tags_text = [f"`{escape_markdown(tag['tag_text'], version=2)}` \({tag['tag_count']}\)" for tag in top_tags]
        text += " ".join(tags_text) + "\n\n"
    
    text += "您可以对他/她进行评价："
    await message.reply_text(text, reply_markup=keyboard, parse_mode='MarkdownV2')

async def build_vote_keyboard(target_id: int):
    # 此函数及以下所有函数都无需改动，它们是通用的
    keyboard = [
        [
            InlineKeyboardButton("推荐 👍", callback_data=f"vote_1_{target_id}"),
            InlineKeyboardButton("拉黑 👎", callback_data=f"vote_-1_{target_id}")
        ],
        [
            InlineKeyboardButton("加入我的收藏 ⭐", callback_data=f"fav_add_{target_id}"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def handle_vote(query, voter, target_id, vote_type):
    if voter.id == target_id:
        await query.answer("你不能给自己投票！", show_alert=True)
        return
    with db_cursor() as cur:
        cur.execute("SELECT vote_type FROM votes WHERE voter_id = %s AND target_id = %s", (voter.id, target_id))
        existing_vote = cur.fetchone()
        if existing_vote and existing_vote['vote_type'] == vote_type:
            await query.answer("你已经投过这个票了。", show_alert=True)
            return
        cur.execute(
            "INSERT INTO votes (voter_id, target_id, vote_type) VALUES (%s, %s, %s) ON CONFLICT (voter_id, target_id) DO UPDATE SET vote_type = EXCLUDED.vote_type;",
            (voter.id, target_id, vote_type)
        )
        if existing_vote:
            cur.execute("UPDATE targets SET upvotes = upvotes + %s, downvotes = downvotes + %s WHERE id = %s", (1 if vote_type == 1 else -1, -1 if vote_type == 1 else 1, target_id))
        else:
            column_to_update = 'upvotes' if vote_type == 1 else 'downvotes'
            cur.execute(f"UPDATE targets SET {column_to_update} = {column_to_update} + 1 WHERE id = %s", (target_id,))
        cur.execute("SELECT id, tag_text FROM tags WHERE tag_type = %s", (vote_type,))
        tags = cur.fetchall()
        tag_keyboard = [InlineKeyboardButton(tag['tag_text'], callback_data=f"tag_{vote_type}_{target_id}_{tag['id']}") for tag in tags]
        keyboard = [tag_keyboard[i:i+2] for i in range(0, len(tag_keyboard), 2)]
        keyboard.append([InlineKeyboardButton("跳过贴标签", callback_data=f"vote_skip_{target_id}")])
        await query.edit_message_text("投票成功！请选择一个标签来描述原因 (可选)：", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_skip_or_apply_tag(query, target_id):
    """完成贴标签或跳过后，刷新信誉面板。"""
    with db_cursor() as cur:
        cur.execute("SELECT * FROM users WHERE id = %s", (target_id,))
        target_user_data = cur.fetchone()
    target_user = User(id=target_user_data['id'], first_name=target_user_data['first_name'], is_bot=False, username=target_user_data['username'])
    
    # 获取原始消息，以便我们可以就地编辑它
    original_message = query.message
    
    # 我们需要一个假的 "reporter" 对象，但它在这里不重要
    fake_reporter = query.from_user
    
    # 复用 _proceed_with_nomination 的文本生成逻辑，但用于编辑消息
    with db_cursor() as cur:
        cur.execute("SELECT upvotes, downvotes FROM targets WHERE id = %s", (target_id,))
        target_data = cur.fetchone()
        cur.execute("""
            SELECT t.tag_text, COUNT(at.tag_id) as tag_count
            FROM applied_tags at JOIN tags t ON at.tag_id = t.id
            WHERE at.vote_target_id = %s GROUP BY t.tag_text
            ORDER BY tag_count DESC LIMIT 5
        """, (target_id,))
        top_tags = cur.fetchall()

    keyboard = await build_vote_keyboard(target_id)
    safe_first_name = escape_markdown(target_user.first_name, version=2)
    safe_username = escape_markdown(target_user.username or 'N/A', version=2)

    text = (
        f"👤 *用户信誉档案: {safe_first_name} \(@{safe_username}\)*\n"
        f"当前状态: \[👍{target_data['upvotes']}\] \[👎{target_data['downvotes']}\]\n\n"
    )
    if top_tags:
        text += "*热门标签:*\n"
        tags_text = [f"`{escape_markdown(tag['tag_text'], version=2)}` \({tag['tag_count']}\)" for tag in top_tags]
        text += " ".join(tags_text) + "\n\n"
    text += "您可以对他/她进行评价："
    
    # 编辑原始消息，而不是发送新消息
    await original_message.edit_text(text, reply_markup=keyboard, parse_mode='MarkdownV2')


async def handle_apply_tag(query, voter, target_id, tag_id):
    with db_cursor() as cur:
        cur.execute("SELECT * from votes WHERE voter_id = %s AND target_id = %s", (voter.id, target_id))
        if not cur.fetchone():
            await query.answer("请先投票！", show_alert=True)
            return
        cur.execute("""
            INSERT INTO applied_tags (vote_voter_id, vote_target_id, tag_id) VALUES (%s, %s, %s)
            ON CONFLICT (vote_voter_id, vote_target_id) DO UPDATE SET tag_id = EXCLUDED.tag_id;
        """, (voter.id, target_id, tag_id))
    await handle_skip_or_apply_tag(query, target_id)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    voter = query.from_user
    await register_user_if_not_exists(voter)
    parts = query.data.split('_')
    action = parts[0]
    
    if action == "vote":
        if parts[1] == "skip":
            await handle_skip_or_apply_tag(query, int(parts[2]))
        else:
            await handle_vote(query, voter, int(parts[2]), int(parts[1]))
    elif action == "tag":
        await handle_apply_tag(query, voter, int(parts[2]), int(parts[3]))
