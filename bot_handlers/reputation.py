import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
import database

logger = logging.getLogger(__name__)

async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles @username queries in groups to show reputation based on evaluations."""
    if not update.message or not update.message.text:
        return

    text = update.message.text
    entities = update.message.entities

    try:
        # Find the first @mention in the message
        mention_entity = next((e for e in entities if e.type == 'mention'), None)
        if not mention_entity:
            return

        target_username = text[mention_entity.offset + 1 : mention_entity.offset + mention_entity.length]
        
        # Get target user's pkid and hidden status from your DB schema
        target_user_data = await database.db_fetch_one(
            "SELECT pkid, is_hidden FROM users WHERE username ILIKE $1", target_username
        )

        if not target_user_data:
            await update.message.reply_text(f"数据库中找不到用户 @{target_username}。")
            return
        
        if target_user_data['is_hidden']:
            await update.message.reply_text(f"用户 @{target_username} 已被管理员隐藏。")
            return

        target_user_pkid = target_user_data['pkid']

        # Calculate score from 'evaluations' table
        recommends = await database.db_fetch_val(
            "SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = $1 AND type = 'recommend'", target_user_pkid
        ) or 0
        warns = await database.db_fetch_val(
            "SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = $1 AND type = 'warn'", target_user_pkid
        ) or 0
        
        score = recommends - warns

        # Get active tags for creating evaluation buttons
        tags = await database.db_fetch_all("SELECT pkid, name, type FROM tags WHERE is_active = TRUE")
        
        keyboard = []
        if tags:
            recommend_buttons = [
                InlineKeyboardButton(f"👍 {tag['name']}", callback_data=f"eval_rec_{tag['pkid']}_{target_user_pkid}")
                for tag in tags if tag['type'] == 'recommend'
            ]
            warn_buttons = [
                InlineKeyboardButton(f"👎 {tag['name']}", callback_data=f"eval_warn_{tag['pkid']}_{target_user_pkid}")
                for tag in tags if tag['type'] == 'warn'
            ]
            if recommend_buttons:
                keyboard.append(recommend_buttons)
            if warn_buttons:
                keyboard.append(warn_buttons)

        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        message_text = (
            f"查询用户 @{target_username} 的评价:\n\n"
            f"👍 **推荐: {recommends} 次**\n"
            f"👎 **警告: {warns} 次**\n"
            f"⭐️ **综合评分: {score}**\n\n"
            "您可以对他/她进行评价:"
        )

        await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error in handle_query: {e}", exc_info=True)
        await update.message.reply_text("查询用户评价时发生错误。")


async def evaluation_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles button presses for evaluations (recommend/warn)."""
    query = update.callback_query
    
    try:
        await query.answer()
        
        # callback_data format: "eval_rec_TAGPKID_TARGETPKID" or "eval_warn_TAGPKID_TARGETPKID"
        _, eval_type, tag_pkid_str, target_user_pkid_str = query.data.split('_')
        tag_pkid = int(tag_pkid_str)
        target_user_pkid = int(target_user_pkid_str)
        
        evaluator_user_id = query.from_user.id

        # Get pkid for the user who clicked the button
        evaluator_user_pkid = await database.get_or_create_user(query.from_user)

        if not evaluator_user_pkid:
            await query.edit_message_text("错误：无法识别您的身份。")
            return
            
        # Prevent self-evaluation
        if evaluator_user_pkid == target_user_pkid:
            await query.answer("您不能评价自己。", show_alert=True)
            return

        # Record the evaluation in the database
        await database.db_execute(
            """
            INSERT INTO evaluations (evaluator_user_pkid, target_user_pkid, tag_pkid, type)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (evaluator_user_pkid, target_user_pkid, tag_pkid) DO UPDATE SET
            type = EXCLUDED.type, created_at = NOW();
            """,
            evaluator_user_pkid, target_user_pkid, tag_pkid, eval_type
        )
        
        tag_name = await database.db_fetch_val("SELECT name FROM tags WHERE pkid = $1", tag_pkid)
        
        await query.edit_message_text(f"✅ 您已成功评价，标签为: **{tag_name}**", parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error in evaluation_callback_handler: {e}", exc_info=True)
        # Use try-except for the edit_message_text in case the message was deleted
        try:
            await query.edit_message_text("处理评价时发生错误。")
        except:
            pass
