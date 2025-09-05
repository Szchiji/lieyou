import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import (
    db_fetch_one, db_execute, db_fetch_all, 
    update_user_activity, is_admin
)
from .utils import schedule_message_deletion

logger = logging.getLogger(__name__)

async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理对用户的查询。
    如果用户不存在，则根据消息实体创建该用户，然后显示其声誉卡片。
    """
    message = update.effective_message
    query_user = update.effective_user
    
    # 记录发起查询的用户活动
    await update_user_activity(query_user.id, query_user.username, query_user.first_name)

    target_user: User = None
    target_username: str = None

    # --- 核心逻辑修改：优先从消息实体中获取被@的用户对象 ---
    if message.entities:
        for entity in message.entities:
            if entity.type == 'mention':
                # 直接从文本中提取 username
                target_username = message.text[entity.offset + 1 : entity.offset + entity.length]
            elif entity.type == 'text_mention' and entity.user:
                # 如果是 text_mention (例如，用户没有用户名)，直接获取用户对象
                target_user = entity.user
                break # 找到了就跳出循环
    
    # 如果是私聊，也处理纯文本
    if not target_user and not target_username and update.effective_chat.type == 'private':
        text = message.text.strip()
        if text.startswith('@'):
            target_username = text[1:]
        elif '查询' in text:
             target_username = text.replace('查询', '').strip().lstrip('@')

    # 如果没有找到任何目标，则退出
    if not target_user and not target_username:
        return

    target_user_id = None
    
    # 如果我们已经通过 text_mention 获取了用户对象
    if target_user:
        target_user_id = target_user.id
        # 顺便更新或创建这个用户的信息
        await update_user_activity(target_user.id, target_user.username, target_user.first_name)
    
    # 如果我们只有用户名
    elif target_username:
        # 尝试从数据库根据用户名查找
        db_user = await db_fetch_one("SELECT id FROM users WHERE username = $1", target_username)
        if db_user:
            target_user_id = db_user['id']
        else:
            # --- 按需创建用户的关键 ---
            # 如果数据库没有，说明这是一个全新的用户被@
            # 我们无法仅凭 username 就获得 user_id，所以这里我们只能提示
            # 注意：Telegram Bot API 的限制，我们无法仅通过 username 获取一个未知的 user_id
            # 只有当用户在消息中被 text_mention (有ID) 或者用户自己与机器人交互时，我们才能获取ID
            # 因此，对于一个从未出现过的 @username, 我们实际上是无法为其创建档案的。
            # 我们能创建档案的，是那些在消息中被正确提及（带ID链接）的用户。
            msg = await message.reply_text(f"我还没有关于 @{target_username} 的信息，需要该用户与机器人互动一次后才能创建档案。")
            await schedule_message_deletion(context, msg.chat_id, msg.message_id, 15)
            return

    if target_user_id:
        await send_reputation_card(message, context, target_user_id)
    # 如果最终还是没有 target_user_id (例如，只有私聊的纯文本username且用户不存在)，则不处理
    elif not target_user:
         msg = await message.reply_text(f"我找不到关于 @{target_username} 的信息。")
         await schedule_message_deletion(context, msg.chat_id, msg.message_id, 15)


async def send_reputation_card(message_or_query, context: ContextTypes.DEFAULT_TYPE, target_user_id: int):
    """构建并发送用户的声誉卡片"""
    is_callback = not isinstance(message_or_query, type(update.effective_message))
    
    if is_callback:
        query = message_or_query.callback_query
        message = query.message
    else:
        message = message_or_query
        query = None

    try:
        card_data = await build_reputation_card_data(target_user_id)
        if not card_data:
            err_msg = "❌ 无法获取该用户的声誉信息。"
            if query:
                await query.answer(err_msg, show_alert=True)
            else:
                await message.reply_text(err_msg)
            return
            
        text = card_data['text']
        keyboard = card_data['keyboard']
        reply_markup = InlineKeyboardMarkup(keyboard)

        if query:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            sent_message = await message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            await schedule_message_deletion(context, sent_message.chat_id, sent_message.message_id)

    except Exception as e:
        logger.error(f"发送声誉卡片失败 (用户ID: {target_user_id}): {e}", exc_info=True)
        err_msg = "❌ 生成声誉卡片时出错。"
        if query:
            await query.answer(err_msg, show_alert=True)
        else:
            await message.reply_text(err_msg)


async def build_reputation_card_data(target_user_id: int) -> dict:
    """构建声誉卡片所需的数据 (文本和按钮)"""
    user_info = await db_fetch_one("SELECT id, username, first_name FROM users WHERE id = $1", target_user_id)
    if not user_info:
        return None

    display_name = user_info['first_name'] or (f"@{user_info['username']}" if user_info['username'] else f"用户 {user_info['id']}")
    
    query = """
    SELECT 
        (SELECT COUNT(*) FROM votes v JOIN tags t ON v.tag_id=t.id WHERE v.target_user_id = $1 AND t.type = 'recommend') as recommend_count,
        (SELECT COUNT(*) FROM votes v JOIN tags t ON v.tag_id=t.id WHERE v.target_user_id = $1 AND t.type = 'block') as block_count,
        (SELECT COUNT(*) FROM favorites WHERE target_user_id = $1) as favorite_count;
    """
    data = await db_fetch_one(query, target_user_id)
    
    recommend_count = data['recommend_count'] or 0
    block_count = data['block_count'] or 0
    favorite_count = data['favorite_count'] or 0
    score = recommend_count - block_count

    text = f"**声誉卡片: {display_name}**\n\n"
    text += f"👍 **推荐**: `{recommend_count}`\n"
    text += f"👎 **警告**: `{block_count}`\n"
    text += f"❤️ **收藏**: `{favorite_count}`\n"
    text += f"--------------------\n"
    text += f"✨ **综合声望**: `{score}`"
    
    keyboard = [
        [
            InlineKeyboardButton("👍 推荐", callback_data=f"vote_recommend_{target_user_id}_1"),
            InlineKeyboardButton("👎 警告", callback_data=f"vote_block_{target_user_id}_1"),
        ],
        [
            InlineKeyboardButton("❤️ 收藏", callback_data=f"add_favorite_{target_user_id}"),
            InlineKeyboardButton("📊 统计", callback_data=f"stats_user_{target_user_id}_1"),
        ]
    ]
    
    return {'text': text, 'keyboard': keyboard}

async def vote_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int, vote_type: str, page: int):
    """显示用于投票的标签列表"""
    query = update.callback_query
    
    tags = await db_fetch_all("SELECT id, name FROM tags WHERE type = $1 ORDER BY name", vote_type)
    if not tags:
        await query.answer(f"❌ 系统中还没有任何{'推荐' if vote_type == 'recommend' else '警告'}标签。", show_alert=True)
        return

    keyboard = []
    for tag in tags:
        keyboard.append([InlineKeyboardButton(tag['name'], callback_data=f"process_vote_{target_user_id}_{tag['id']}")])
    
    keyboard.append([InlineKeyboardButton("🔙 返回声誉卡片", callback_data=f"back_to_rep_card_{target_user_id}")])
    
    vote_text = "👍 请选择一个**推荐**标签：" if vote_type == "recommend" else "👎 请选择一个**警告**标签："
    
    await query.edit_message_text(vote_text, reply_markup=InlineKeyboardMarkup(keyboard))


async def process_vote(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int, tag_id: str):
    """处理用户的投票"""
    query = update.callback_query
    voter_id = query.from_user.id
    tag_id = int(tag_id)

    if voter_id == target_user_id:
        await query.answer("❌ 你不能给自己投票。", show_alert=True)
        return

    try:
        await db_execute(
            """
            INSERT INTO votes (voter_user_id, target_user_id, tag_id, message_id, chat_id)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (voter_user_id, target_user_id, tag_id) DO NOTHING;
            """,
            voter_id, target_user_id, tag_id, query.message.message_id, query.message.chat_id
        )
        await query.answer("✅ 投票成功！", show_alert=True)
    except Exception as e:
        logger.error(f"投票处理失败: {e}")
        await query.answer("❌ 投票失败，发生未知错误。", show_alert=True)
    
    await back_to_rep_card(update, context, target_user_id)


async def back_to_rep_card(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int):
    """从其他菜单返回到声誉卡片"""
    await send_reputation_card(update, context, target_user_id)
