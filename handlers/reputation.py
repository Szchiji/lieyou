import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import (
    db_fetch_one, db_execute, db_fetch_all, get_or_create_user, db_fetch_val
)
from .utils import schedule_message_deletion

logger = logging.getLogger(__name__)

async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    is_edited = bool(update.edited_message)

    query_user = update.effective_user
    await get_or_create_user(user_id=query_user.id, username=query_user.username, first_name=query_user.first_name)
    
    target_user_from_entity: User = None
    target_username_from_text: str = None
    
    if message.entities:
        for entity in message.entities:
            if entity.type == 'mention':
                target_username_from_text = message.text[entity.offset + 1 : entity.offset + entity.length]
            elif entity.type == 'text_mention' and entity.user:
                target_user_from_entity = entity.user
                break
    
    if not target_user_from_entity and not target_username_from_text:
        return

    # --- 核心简化：直接调用 get_or_create_user，它会处理一切 ---
    target_user_db_info = None
    if target_user_from_entity:
        target_user_db_info = await get_or_create_user(user_id=target_user_from_entity.id, username=target_user_from_entity.username, first_name=target_user_from_entity.first_name)
    elif target_username_from_text:
        target_user_db_info = await get_or_create_user(username=target_username_from_text)
        
    if target_user_db_info:
        await send_reputation_card(update, context, target_user_db_info['pkid'], is_edited=is_edited)
    else:
        # 理论上，在新逻辑下这里几乎不可能到达，但作为保险
        error_text = "❌ 创建或查询用户档案时发生未知错误。"
        if is_edited:
            bot_reply = context.user_data.get(f"reply_to_{message.message_id}")
            if bot_reply:
                await context.bot.edit_message_text(error_text, chat_id=bot_reply['chat_id'], message_id=bot_reply['message_id'])
        else:
            await message.reply_text(error_text)

# ... send_reputation_card 和文件的其余部分与上一版本完全相同 ...
async def send_reputation_card(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, origin: str = "", is_edited: bool = False):
    query = update.callback_query
    message = query.message if query else update.effective_message

    try:
        current_user_id = update.effective_user.id
        card_data = await build_reputation_card_data(target_user_pkid, current_user_id, origin)
        if not card_data:
            raise ValueError("无法构建声誉卡片数据")
        
        reply_markup = InlineKeyboardMarkup(card_data['keyboard'])

        bot_reply_key = f"reply_to_{message.message_id}"

        if query:
            if message.text != card_data['text'] or message.reply_markup != reply_markup:
                await query.edit_message_text(card_data['text'], reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            else:
                await query.answer("数据已是最新。")
        elif is_edited:
            bot_reply = context.user_data.get(bot_reply_key)
            if bot_reply:
                try:
                    await context.bot.edit_message_text(card_data['text'], chat_id=bot_reply['chat_id'], message_id=bot_reply['message_id'], reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                except Exception as e:
                    logger.warning(f"编辑声誉卡片失败: {e}, 将重新发送。")
                    sent_message = await message.reply_text(card_data['text'], reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                    context.user_data[bot_reply_key] = {'chat_id': sent_message.chat_id, 'message_id': sent_message.message_id}
            else:
                sent_message = await message.reply_text(card_data['text'], reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                context.user_data[bot_reply_key] = {'chat_id': sent_message.chat_id, 'message_id': sent_message.message_id}
        else:
            sent_message = await message.reply_text(card_data['text'], reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            context.user_data[bot_reply_key] = {'chat_id': sent_message.chat_id, 'message_id': sent_message.message_id}
            if message.chat.type != 'private':
                await schedule_message_deletion(context, sent_message.chat_id, sent_message.message_id)

    except Exception as e:
        logger.error(f"发送声誉卡片失败 (pkid: {target_user_pkid}): {e}", exc_info=True)
        err_msg = "❌ 生成声誉卡片时出错。"
        if query: await query.answer(err_msg, show_alert=True)
        elif message: await message.reply_text(err_msg)

async def build_reputation_card_data(target_user_pkid: int, current_user_id: int, origin: str = "") -> dict:
    sql = """
    SELECT
        u.pkid,
        u.first_name,
        u.username,
        (SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = u.pkid AND type = 'recommend') AS recommend_count,
        (SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = u.pkid AND type = 'block') AS block_count,
        (SELECT COUNT(*) FROM favorites WHERE target_user_pkid = u.pkid) AS favorite_count,
        EXISTS (
            SELECT 1 FROM favorites 
            WHERE target_user_pkid = u.pkid 
            AND user_pkid = (SELECT pkid FROM users WHERE id = $2 LIMIT 1)
        ) AS is_favorited
    FROM
        users u
    WHERE
        u.pkid = $1;
    """
    user_info = await db_fetch_one(sql, target_user_pkid, current_user_id)
    if not user_info: return None

    first_name = user_info.get('first_name')
    username = user_info.get('username')
    if first_name and first_name != username:
        display_name = f"{first_name} (@{username})" if username else first_name
    elif username:
        display_name = f"@{username}"
    else:
        display_name = f"用户 {user_info['pkid']}"

    recommend_count = user_info.get('recommend_count', 0)
    block_count = user_info.get('block_count', 0)
    favorite_count = user_info.get('favorite_count', 0)
    is_favorited = user_info.get('is_favorited', False)
    score = recommend_count - block_count

    text = (f"**声誉卡片: {display_name}**\n\n"
            f"👍 **推荐**: `{recommend_count}`\n"
            f"👎 **警告**: `{block_count}`\n"
            f"❤️ **收藏**: `{favorite_count}`\n"
            f"--------------------\n"
            f"✨ **综合声望**: `{score}`")
    
    if is_favorited:
        favorite_button = InlineKeyboardButton("💔 取消收藏", callback_data=f"remove_favorite_{target_user_pkid}_{origin}")
    else:
        favorite_button = InlineKeyboardButton("❤️ 收藏", callback_data=f"add_favorite_{target_user_pkid}_{origin}")
        
    keyboard = [
        [InlineKeyboardButton("👍 推荐", callback_data=f"vote_recommend_{target_user_pkid}_{origin}"),
         InlineKeyboardButton("👎 警告", callback_data=f"vote_block_{target_user_pkid}_{origin}")],
        [favorite_button,
         InlineKeyboardButton("📊 统计", callback_data=f"stats_user_{target_user_pkid}_1_{origin}")]
    ]
    
    if origin and origin.startswith("fav_"):
        page = origin.split('_')[1]
        keyboard.append([InlineKeyboardButton("🔙 返回收藏列表", callback_data=f"my_favorites_{page}")])
    
    return {'text': text, 'keyboard': keyboard}

async def vote_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, vote_type: str, origin: str):
    query = update.callback_query
    tags = await db_fetch_all("SELECT id, name FROM tags WHERE type = $1 ORDER BY name", vote_type)
    if not tags:
        await query.answer(f"❌ 系统中还没有任何{'推荐' if vote_type == 'recommend' else '警告'}标签。", show_alert=True)
        return

    keyboard = [[InlineKeyboardButton(tag['name'], callback_data=f"process_vote_{target_user_pkid}_{tag['id']}_{origin}")] for tag in tags]
    keyboard.append([InlineKeyboardButton("🔙 返回声誉卡片", callback_data=f"back_to_rep_card_{target_user_pkid}_{origin}")])
    
    vote_text = "👍 请选择一个**推荐**理由：" if vote_type == "recommend" else "👎 请选择一个**警告**理由："
    await query.edit_message_text(vote_text, reply_markup=InlineKeyboardMarkup(keyboard))

async def process_vote(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, tag_id: int, origin: str):
    query = update.callback_query
    voter = await get_or_create_user(user_id=query.from_user.id)
    if voter['pkid'] == target_user_pkid:
        await query.answer("❌ 你不能给自己投票。", show_alert=True)
        return

    tag_info = await db_fetch_one("SELECT type FROM tags WHERE id = $1", tag_id)
    if not tag_info:
        await query.answer("❌ 无效的标签。", show_alert=True)
        return

    try:
        await db_execute(
            """INSERT INTO evaluations (voter_user_pkid, target_user_pkid, tag_id, type) VALUES ($1, $2, $3, $4)
               ON CONFLICT (voter_user_pkid, target_user_pkid) DO UPDATE SET tag_id = EXCLUDED.tag_id, type = EXCLUDED.type, updated_at = NOW()""",
            voter['pkid'], target_user_pkid, tag_id, tag_info['type'])
        await query.answer("✅ 评价成功！", show_alert=False)
    except Exception as e:
        logger.error(f"评价处理失败: {e}", exc_info=True)
        await query.answer("❌ 评价失败。", show_alert=True)
    
    await back_to_rep_card(update, context, target_user_pkid, origin)

async def back_to_rep_card(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, origin: str):
    await send_reputation_card(update, context, target_user_pkid, origin)
