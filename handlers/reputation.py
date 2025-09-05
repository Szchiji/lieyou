import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import (
    db_fetch_one, db_execute, db_fetch_all, get_or_create_user
)
from .utils import schedule_message_deletion

logger = logging.getLogger(__name__)

async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理对用户的查询。使用 get_or_create_user 来支持纯文本用户名。
    """
    message = update.effective_message
    query_user = update.effective_user
    
    # 记录发起查询的用户活动
    await get_or_create_user(user_id=query_user.id, username=query_user.username, first_name=query_user.first_name)

    target_user_from_entity: User = None
    target_username_from_text: str = None

    # 从消息实体中解析
    if message.entities:
        for entity in message.entities:
            if entity.type == 'mention':
                target_username_from_text = message.text[entity.offset + 1 : entity.offset + entity.length]
            elif entity.type == 'text_mention' and entity.user:
                target_user_from_entity = entity.user
                break
    
    # 如果是私聊，也处理纯文本
    if not target_user_from_entity and not target_username_from_text and update.effective_chat.type == 'private':
        text = message.text.strip()
        if text.startswith('@'):
            target_username_from_text = text[1:]
        elif '查询' in text:
             target_username_from_text = text.replace('查询', '').strip().lstrip('@')
    
    # 获取或创建目标用户
    target_user_db_info = None
    if target_user_from_entity:
        target_user_db_info = await get_or_create_user(
            user_id=target_user_from_entity.id,
            username=target_user_from_entity.username,
            first_name=target_user_from_entity.first_name
        )
    elif target_username_from_text:
        target_user_db_info = await get_or_create_user(username=target_username_from_text)
    
    # 如果成功获取或创建了用户，则显示声誉卡片
    if target_user_db_info:
        await send_reputation_card(message, context, target_user_db_info['pkid'])
    elif not message.reply_to_message: # 避免对普通消息回复
        await message.reply_text("请 @一个用户或输入用户名来查询。")

async def send_reputation_card(message_or_query, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int):
    """构建并发送用户的声誉卡片，使用 pkid"""
    is_callback = not isinstance(message_or_query, type(update.effective_message))
    
    if is_callback:
        query = message_or_query.callback_query; message = query.message
    else:
        message = message_or_query; query = None

    try:
        card_data = await build_reputation_card_data(target_user_pkid)
        if not card_data:
            raise ValueError("无法构建声誉卡片数据")

        reply_markup = InlineKeyboardMarkup(card_data['keyboard'])
        if query:
            await query.edit_message_text(card_data['text'], reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            sent_message = await message.reply_text(card_data['text'], reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            await schedule_message_deletion(context, sent_message.chat_id, sent_message.message_id)

    except Exception as e:
        logger.error(f"发送声誉卡片失败 (pkid: {target_user_pkid}): {e}", exc_info=True)
        err_msg = "❌ 生成声誉卡片时出错。"
        if query: await query.answer(err_msg, show_alert=True)
        else: await message.reply_text(err_msg)

async def build_reputation_card_data(target_user_pkid: int) -> dict:
    """构建声誉卡片数据，使用 pkid"""
    user_info = await db_fetch_one("SELECT * FROM users WHERE pkid = $1", target_user_pkid)
    if not user_info: return None

    display_name = user_info['first_name'] or (f"@{user_info['username']}" if user_info['username'] else f"用户 {user_info['id']}")
    
    query = """
    SELECT 
        (SELECT COUNT(*) FROM votes v JOIN tags t ON v.tag_id=t.id WHERE v.target_user_pkid = $1 AND t.type = 'recommend') as recommend_count,
        (SELECT COUNT(*) FROM votes v JOIN tags t ON v.tag_id=t.id WHERE v.target_user_pkid = $1 AND t.type = 'block') as block_count,
        (SELECT COUNT(*) FROM favorites WHERE target_user_pkid = $1) as favorite_count;
    """
    data = await db_fetch_one(query, target_user_pkid)
    
    score = (data['recommend_count'] or 0) - (data['block_count'] or 0)
    text = (
        f"**声誉卡片: {display_name}**\n\n"
        f"👍 **推荐**: `{data['recommend_count'] or 0}`\n"
        f"👎 **警告**: `{data['block_count'] or 0}`\n"
        f"❤️ **收藏**: `{data['favorite_count'] or 0}`\n"
        f"--------------------\n"
        f"✨ **综合声望**: `{score}`"
    )
    
    keyboard = [
        [InlineKeyboardButton("👍 推荐", callback_data=f"vote_recommend_{target_user_pkid}_1"), InlineKeyboardButton("👎 警告", callback_data=f"vote_block_{target_user_pkid}_1")],
        [InlineKeyboardButton("❤️ 收藏", callback_data=f"add_favorite_{target_user_pkid}"), InlineKeyboardButton("📊 统计", callback_data=f"stats_user_{target_user_pkid}_1")]
    ]
    return {'text': text, 'keyboard': keyboard}

async def vote_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, vote_type: str, page: int):
    """显示投票标签列表，使用 pkid"""
    query = update.callback_query
    tags = await db_fetch_all("SELECT id, name FROM tags WHERE type = $1 ORDER BY name", vote_type)
    if not tags:
        await query.answer(f"❌ 系统中还没有任何{'推荐' if vote_type == 'recommend' else '警告'}标签。", show_alert=True)
        return

    keyboard = [[InlineKeyboardButton(tag['name'], callback_data=f"process_vote_{target_user_pkid}_{tag['id']}")] for tag in tags]
    keyboard.append([InlineKeyboardButton("🔙 返回声誉卡片", callback_data=f"back_to_rep_card_{target_user_pkid}")])
    
    vote_text = "👍 请选择一个**推荐**标签：" if vote_type == "recommend" else "👎 请选择一个**警告**标签："
    await query.edit_message_text(vote_text, reply_markup=InlineKeyboardMarkup(keyboard))

async def process_vote(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, tag_id: str):
    """处理投票，使用 pkid"""
    query = update.callback_query
    voter = await get_or_create_user(user_id=query.from_user.id)
    tag_id = int(tag_id)

    if voter['pkid'] == target_user_pkid:
        await query.answer("❌ 你不能给自己投票。", show_alert=True)
        return

    try:
        await db_execute(
            """
            INSERT INTO votes (voter_user_pkid, target_user_pkid, tag_id, message_id, chat_id)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (voter_user_pkid, target_user_pkid, tag_id) DO NOTHING;
            """,
            voter['pkid'], target_user_pkid, tag_id, query.message.message_id, query.message.chat_id
        )
        await query.answer("✅ 投票成功！", show_alert=True)
    except Exception as e:
        logger.error(f"投票处理失败: {e}", exc_info=True)
        await query.answer("❌ 投票失败，发生未知错误。", show_alert=True)
    
    await back_to_rep_card(update, context, target_user_pkid)

async def back_to_rep_card(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int):
    """返回声誉卡片，使用 pkid"""
    await send_reputation_card(update, context, target_user_pkid)
