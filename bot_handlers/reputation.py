import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
import database

logger = logging.getLogger(__name__)

async def reputation_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the +1/-1 button presses."""
    query = update.callback_query
    await query.answer()

    try:
        data = query.data.split('_')
        action = data[1]
        target_user_id = int(data[2])
        source_user_id = int(data[3])

        if source_user_id == query.from_user.id:
            await query.answer("您不能给自己加/减分。", show_alert=True)
            return

        change = 1 if action == 'up' else -1
        
        await database.db_execute(
            """
            INSERT INTO reputation_events (source_user_id, target_user_id, change)
            VALUES ($1, $2, $3)
            ON CONFLICT (source_user_id, target_user_id) DO UPDATE
            SET change = $3, created_at = NOW();
            """,
            source_user_id, target_user_id, change
        )

        new_score = await database.db_fetch_val(
            "SELECT SUM(change) FROM reputation_events WHERE target_user_id = $1",
            target_user_id
        ) or 0

        target_user = await context.bot.get_chat_member(query.message.chat.id, target_user_id)
        text = f"对 @{target_user.user.username} 的评价已更新。\n当前总分: {new_score}"
        
        await query.edit_message_text(text)

    except Exception as e:
        logger.error(f"Error in reputation callback: {e}", exc_info=True)
        await query.answer("处理时发生错误。", show_alert=True)

async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles @username queries in groups to show reputation."""
    if not update.message or not update.message.text:
        return

    text = update.message.text
    entities = update.message.entities

    if not entities or entities[0].type != 'mention':
        return

    entity = entities[0]
    target_username = text[entity.offset + 1 : entity.offset + entity.length]

    user_data = await database.db_fetch_row("SELECT id, is_hidden FROM users WHERE username ILIKE $1", target_username)

    if user_data and not user_data['is_hidden']:
        target_user_id = user_data['id']
        score = await database.db_fetch_val("SELECT SUM(change) FROM reputation_events WHERE target_user_id = $1", target_user_id) or 0
        
        keyboard = [
            [
                InlineKeyboardButton("👍 +1", callback_data=f"rep_up_{target_user_id}_{update.effective_user.id}"),
                InlineKeyboardButton("👎 -1", callback_data=f"rep_down_{target_user_id}_{update.effective_user.id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"查询用户 @{target_username} 的信誉分数:\n\n**总分: {score}**\n\n您可以对他/她的信誉进行评价：",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        # --- THIS IS THE FIX ---
        # We simply remove the 'quote=True' argument.
        # The .reply_text() method quotes the original message by default.
        await update.message.reply_text(f"找不到用户 @{target_username} 或该用户已被管理员隐藏。")
