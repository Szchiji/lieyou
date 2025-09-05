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
    
    if not target_user_from_entity and not target_username_from_text and update.effective_chat.type == 'private':
        text = message.text.strip()
        if text.startswith('@'):
            target_username_from_text = text[1:]
        elif '查询' in text:
            target_username_from_text = text.replace('查询', '').strip().lstrip('@')

    if not target_user_from_entity and not target_username_from_text:
        return

    target_user_db_info = None
    if target_user_from_entity:
        target_user_db_info = await get_or_create_user(user_id=target_user_from_entity.id, username=target_user_from_entity.username, first_name=target_user_from_entity.first_name)
    elif target_username_from_text:
        target_user_db_info = await get_or_create_user(username=target_username_from_text)
        
    if target_user_db_info:
        await send_reputation_card(message, context, target_user_db_info['pkid'])
    else:
        await message.reply_text("❌ 无法创建或查询该用户档案。")

async def send_reputation_card(message_or_query, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, origin: str = ""):
    is_callback = isinstance(message_or_query, Update)
    if is_callback:
        query = message_or_query.callback_query
        message = query.message
    else:
        message = message_or_query
        query = None

    try:
        card_data = await build_reputation_card_data(target_user_pkid, origin)
        if not card_data:
            raise ValueError("无法构建声誉卡片数据")
        
        reply_markup = InlineKeyboardMarkup(card_data['keyboard'])

        if query:
            if message.text != card_data['text'] or message.reply_markup != reply_markup:
                await query.edit_message_text(card_data['text'], reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            else:
                await query.answer("数据已是最新。") # 如果内容无变化，仅作提示
        else:
            sent_message = await message.reply_text(card_data['text'], reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            if origin != "fav_refresh":
                await schedule_message_deletion(context, sent_message.chat_id, sent_message.message_id)

    except Exception as e:
        logger.error(f"发送声誉卡片失败 (pkid: {target_user_pkid}): {e}", exc_info=True)
        err_msg = "❌ 生成声誉卡片时出错。"
        if query:
            await query.answer(err_msg, show_alert=True)
        elif message:
            await message.reply_text(err_msg)

async def build_reputation_card_data(target_user_pkid: int, origin: str = "") -> dict:
    # --- 性能优化：将4次查询合并为1次 ---
    sql = """
    SELECT
        u.pkid,
        u.first_name,
        u.username,
        (SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = u.pkid AND type = 'recommend') AS recommend_count,
        (SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = u.pkid AND type = 'block') AS block_count,
        (SELECT COUNT(*) FROM favorites WHERE target_user_pkid = u.pkid) AS favorite_count
    FROM
        users u
    WHERE
        u.pkid = $1;
    """
    user_info = await db_fetch_one(sql, target_user_pkid)
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
    score = recommend_count - block_count

    text = (f"**声誉卡片: {display_name}**\n\n"
            f"👍 **推荐**: `{recommend_count}`\n"
            f"👎 **警告**: `{block_count}`\n"
            f"❤️ **收藏**: `{favorite_count}`\n"
            f"--------------------\n"
            f"✨ **综合声望**: `{score}`")
    
    keyboard = [
        [InlineKeyboardButton("👍 推荐", callback_data=f"vote_recommend_{target_user_pkid}_{origin}"),
         InlineKeyboardButton("👎 警告", callback_data=f"vote_block_{target_user_pkid}_{origin}")],
        [InlineKeyboardButton("❤️ 收藏", callback_data=f"add_favorite_{target_user_pkid}_{origin}"),
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
    if not voter:
        await query.answer("❌ 无法识别您的身份。", show_alert=True)
        return

    if voter['pkid'] == target_user_pkid:
        await query.answer("❌ 你不能给自己投票。", show_alert=True)
        return

    tag_info = await db_fetch_one("SELECT type FROM tags WHERE id = $1", tag_id)
    if not tag_info:
        await query.answer("❌ 无效的标签。", show_alert=True)
        return

    try:
        sql = """
            INSERT INTO evaluations (voter_user_pkid, target_user_pkid, tag_id, type)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (voter_user_pkid, target_user_pkid)
            DO UPDATE SET tag_id = EXCLUDED.tag_id, type = EXCLUDED.type, updated_at = NOW()
            RETURNING id;
        """
        result = await db_fetch_val(sql, voter['pkid'], target_user_pkid, tag_id, tag_info['type'])
        if result:
            await query.answer("✅ 评价成功！", show_alert=True)
        else:
            raise Exception("评价写入失败")

    except Exception as e:
        logger.error(f"评价处理失败: {e}", exc_info=True)
        await query.answer("❌ 评价失败，发生未知错误。", show_alert=True)
    
    await back_to_rep_card(update, context, target_user_pkid, origin)

async def back_to_rep_card(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, origin: str):
    await send_reputation_card(update, context, target_user_pkid, origin)
