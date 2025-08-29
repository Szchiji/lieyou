from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.ext import ContextTypes
from database import db_cursor
import logging

logger = logging.getLogger(__name__)

async def register_user_if_not_exists(user: User):
    """确保用户存在于数据库中。"""
    with db_cursor() as cur:
        cur.execute("SELECT id FROM users WHERE id = %s", (user.id,))
        if cur.fetchone() is None:
            cur.execute(
                "INSERT INTO users (id, username, first_name) VALUES (%s, %s, %s)",
                (user.id, user.username, user.first_name)
            )
            logger.info(f"新用户 {user.first_name} ({user.id}) 已注册。")

async def handle_mention(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理消息中 @username 的提及，用于提名。"""
    message = update.effective_message
    reporter = update.effective_user
    
    # 确保提名者已注册
    await register_user_if_not_exists(reporter)

    entities = message.entities
    mentioned_users = []
    for entity in entities:
        if entity.type == 'mention':
            username = message.text[entity.offset:entity.offset+entity.length]
            if username.startswith('@'):
                username = username[1:]
            
            # 这里我们无法直接从 username 获取 user_id，这是一个Telegram Bot API的限制
            # 我们先将 username 存起来，后续通过某种方式（如用户与机器人交互）获取ID
            # 简化处理：我们直接用 username 作为标识，但这不是最稳健的做法
            # 一个更好的做法是让用户回复某个人的消息来提名
            await message.reply_text(f"你提名了 @{username}。\n注意：由于API限制，机器人需要 @{username} 与机器人私聊一次完成注册后，才能正式被评价。")
            return # 暂时简化处理

# ... 实际项目中，处理提名的更好方式是回复消息 ...

async def handle_nomination_via_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """通过回复一个用户的消息来进行提名。"""
    message = update.effective_message
    if not message.reply_to_message:
        await message.reply_text("请通过回复一个人的消息来提名他/她。")
        return

    reporter = message.from_user
    target = message.reply_to_message.from_user

    if reporter.id == target.id:
        await message.reply_text("你不能提名自己！")
        return
    
    if target.is_bot:
        await message.reply_text("你不能提名一个机器人。")
        return

    # 注册双方
    await register_user_if_not_exists(reporter)
    await register_user_if_not_exists(target)

    with db_cursor() as cur:
        cur.execute("SELECT * FROM targets WHERE id = %s", (target.id,))
        target_data = cur.fetchone()

        if target_data is None:
            cur.execute(
                "INSERT INTO targets (id, username, first_name, first_reporter_id) VALUES (%s, %s, %s, %s)",
                (target.id, target.username, target.first_name, reporter.id)
            )
            logger.info(f"用户 {reporter.id} 提名了新目标 {target.id}")
            target_data = {'id': target.id, 'upvotes': 0, 'downvotes': 0}


        keyboard = await build_vote_keyboard(target.id)
        await message.reply_to_message.reply_text(
            f"👤 **目标已锁定: {target.full_name} (@{target.username})**\n"
            f"当前状态: [推荐: {target_data['upvotes']}] [拉黑: {target_data['downvotes']}]\n\n"
            "请社群成员进行评价：",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )

# ... 投票和按钮逻辑 ...
async def build_vote_keyboard(target_id: int):
    """构建投票键盘"""
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

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """统一处理所有按钮点击。"""
    query = update.callback_query
    await query.answer()

    voter = query.from_user
    await register_user_if_not_exists(voter)

    parts = query.data.split('_')
    action = parts[0]
    
    if action == "vote":
        vote_type = int(parts[1])
        target_id = int(parts[2])
        await handle_vote(query, voter, target_id, vote_type)
    
    elif action == "tag":
        vote_type = int(parts[1])
        target_id = int(parts[2])
        tag_id = int(parts[3])
        await handle_apply_tag(query, voter, target_id, tag_id, vote_type)

    elif action == "fav":
        # 交给 profile 模块处理
        from .profile import handle_favorite_button
        await handle_favorite_button(query, voter)
        
    elif action.startswith("leaderboard") or action.startswith("admin"):
        # 这些是其他模块的，这里忽略，让它们自己的处理器处理
        pass

async def handle_vote(query, voter, target_id, vote_type):
    """处理投票逻辑。"""
    if voter.id == target_id:
        await query.answer("你不能给自己投票！", show_alert=True)
        return

    with db_cursor() as cur:
        # 检查是否已投过票
        cur.execute("SELECT vote_type FROM votes WHERE voter_id = %s AND target_id = %s", (voter.id, target_id))
        existing_vote = cur.fetchone()

        if existing_vote and existing_vote['vote_type'] == vote_type:
            await query.answer("你已经投过这个票了。", show_alert=True)
            return

        # 插入或更新投票
        cur.execute(
            """
            INSERT INTO votes (voter_id, target_id, vote_type) VALUES (%s, %s, %s)
            ON CONFLICT (voter_id, target_id) DO UPDATE SET vote_type = EXCLUDED.vote_type;
            """,
            (voter.id, target_id, vote_type)
        )
        
        # 更新票数统计
        if existing_vote: # 更改投票
            if vote_type == 1: # from -1 to 1
                cur.execute("UPDATE targets SET upvotes = upvotes + 1, downvotes = downvotes - 1 WHERE id = %s", (target_id,))
            else: # from 1 to -1
                cur.execute("UPDATE targets SET upvotes = upvotes - 1, downvotes = downvotes + 1 WHERE id = %s", (target_id,))
        else: # 新投票
            if vote_type == 1:
                cur.execute("UPDATE targets SET upvotes = upvotes + 1 WHERE id = %s", (target_id,))
            else:
                cur.execute("UPDATE targets SET downvotes = downvotes + 1 WHERE id = %s", (target_id,))

        # 获取标签选项
        cur.execute("SELECT id, tag_text FROM tags WHERE tag_type = %s", (vote_type,))
        tags = cur.fetchall()
        
        tag_keyboard = [
            InlineKeyboardButton(
                tag['tag_text'], 
                callback_data=f"tag_{vote_type}_{target_id}_{tag['id']}"
            ) for tag in tags
        ]
        
        keyboard = [tag_keyboard[i:i+2] for i in range(0, len(tag_keyboard), 2)]

        await query.edit_message_text(
            f"投票成功！请选择一个标签来描述原因：",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def handle_apply_tag(query, voter, target_id, tag_id, vote_type):
    """处理应用标签的逻辑。"""
    with db_cursor() as cur:
        # 确保投票记录存在
        cur.execute("SELECT * from votes WHERE voter_id = %s AND target_id = %s", (voter.id, target_id))
        if not cur.fetchone():
            await query.answer("请先投票！", show_alert=True)
            return
        
        # 插入或更新标签
        cur.execute(
            "DELETE FROM applied_tags WHERE vote_voter_id = %s AND vote_target_id = %s",
            (voter.id, target_id)
        )
        cur.execute(
            "INSERT INTO applied_tags (vote_voter_id, vote_target_id, tag_id) VALUES (%s, %s, %s)",
            (voter.id, target_id, tag_id)
        )

        # 获取目标最新信息并更新原始消息
        cur.execute("SELECT * FROM targets WHERE id = %s", (target_id,))
        target_data = cur.fetchone()
        cur.execute("SELECT first_name FROM users WHERE id = %s", (target_id,))
        target_user = cur.fetchone()
        
        keyboard = await build_vote_keyboard(target_id)
        await query.edit_message_text(
            f"✅ 感谢您的评价！\n\n"
            f"👤 **目标: {target_user['first_name']} (@{target_data['username']})**\n"
            f"当前状态: [推荐: {target_data['upvotes']}] [拉黑: {target_data['downvotes']}]",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
