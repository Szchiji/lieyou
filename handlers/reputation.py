from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User, MessageEntity
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown
from database import db_cursor
import logging

logger = logging.getLogger(__name__)

async def register_user_if_not_exists(user: User):
    """确保用户存在于数据库中，并更新其用户名。"""
    if not user or user.is_bot:
        return
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (id, username, first_name) VALUES (%s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name;
            """,
            (user.id, user.username, user.first_name)
        )

async def handle_mention_nomination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 '评价 @username' 格式的提名。"""
    message = update.effective_message
    reporter = update.effective_user
    
    await register_user_if_not_exists(reporter)

    target_username = None
    for entity in message.entities:
        if entity.type == MessageEntity.MENTION:
            target_username = message.text[entity.offset + 1 : entity.offset + entity.length]
            break

    if not target_username:
        if message.text.lower().startswith(('评价', 'nominate')):
             await message.reply_text("请提供一个 @username。用法: `评价 @username`", parse_mode='MarkdownV2')
        return

    with db_cursor() as cur:
        cur.execute("SELECT * FROM users WHERE username = %s", (target_username,))
        target_user_data = cur.fetchone()

    if target_user_data:
        target_id = target_user_data['id']
        if reporter.id == target_id:
            await message.reply_text("你不能评价自己！")
            return
        
        await _proceed_with_nomination(
            message, reporter,
            target_id=target_id,
            target_username=target_user_data['username'],
            target_first_name=target_user_data['first_name']
        )
    else:
        # 修正：对用户输入的内容进行转义
        safe_username = escape_markdown(target_username, version=2)
        await message.reply_text(
            f"❌ 我还不认识 *@{safe_username}*。\n\n"
            f"请先让 *@_@{safe_username}* 与我私聊一次，我才能认识他/她。",
            parse_mode='MarkdownV2'
        )

async def _proceed_with_nomination(message, reporter, target_id, target_username, target_first_name):
    """核心逻辑：创建提名面板。"""
    with db_cursor() as cur:
        cur.execute("SELECT * FROM targets WHERE id = %s", (target_id,))
        target_data = cur.fetchone()

        if target_data is None:
            cur.execute(
                "INSERT INTO targets (id, username, first_name, first_reporter_id) VALUES (%s, %s, %s, %s)",
                (target_id, target_username, target_first_name, reporter.id)
            )
            cur.execute("SELECT * FROM targets WHERE id = %s", (target_id,))
            target_data = cur.fetchone()

        keyboard = await build_vote_keyboard(target_id)
        
        # 修正：对所有用户输入的内容进行转义
        safe_first_name = escape_markdown(target_first_name, version=2)
        safe_username = escape_markdown(target_username, version=2)

        await message.reply_text(
            f"👤 *目标已锁定: {safe_first_name} \(@{safe_username}\)*\n"
            f"当前状态: \[推荐: {target_data['upvotes']}\] \[拉黑: {target_data['downvotes']}\]\n\n"
            "请社群成员进行评价：",
            reply_markup=keyboard,
            parse_mode='MarkdownV2'
        )

# --- 投票和按钮逻辑 (大部分不变) ---

async def build_vote_keyboard(target_id: int):
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
        # ... (内部逻辑不变) ...
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

async def handle_skip_tag(query, target_id):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM targets WHERE id = %s", (target_id,))
        target_data = cur.fetchone()
        cur.execute("SELECT first_name, username FROM users WHERE id = %s", (target_id,))
        target_user = cur.fetchone()

        keyboard = await build_vote_keyboard(target_id)
        
        # 修正：转义
        safe_first_name = escape_markdown(target_user['first_name'], version=2)
        safe_username = escape_markdown(target_user['username'], version=2)

        await query.edit_message_text(
            f"✅ 感谢您的评价！\n\n👤 *目标: {safe_first_name} \(@{safe_username}\)*\n当前状态: \[推荐: {target_data['upvotes']}\] \[拉黑: {target_data['downvotes']}\]",
            reply_markup=keyboard, parse_mode='MarkdownV2'
        )

async def handle_apply_tag(query, voter, target_id, tag_id, vote_type):
    with db_cursor() as cur:
        # ... (内部逻辑不变) ...
        cur.execute("SELECT * from votes WHERE voter_id = %s AND target_id = %s", (voter.id, target_id))
        if not cur.fetchone():
            await query.answer("请先投票！", show_alert=True)
            return
        
        cur.execute("DELETE FROM applied_tags WHERE vote_voter_id = %s AND vote_target_id = %s", (voter.id, target_id))
        cur.execute("INSERT INTO applied_tags (vote_voter_id, vote_target_id, tag_id) VALUES (%s, %s, %s)", (voter.id, target_id, tag_id))
        await handle_skip_tag(query, target_id)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    voter = query.from_user
    await register_user_if_not_exists(voter)
    parts = query.data.split('_')
    action = parts[0]
    
    if action == "vote":
        if parts[1] == "skip":
            await handle_skip_tag(query, int(parts[2]))
        else:
            await handle_vote(query, voter, int(parts[2]), int(parts[1]))
    elif action == "tag":
        await handle_apply_tag(query, voter, int(parts[2]), int(parts[3]), int(parts[1]))
    elif action == "fav":
        from .profile import handle_favorite_button
        await handle_favorite_button(query, voter)
