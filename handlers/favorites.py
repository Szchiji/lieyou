import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction
# 导入 reputation handler 中的函数以刷新视图
from handlers.reputation import get_reputation_summary, build_summary_view

logger = logging.getLogger(__name__)

async def my_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """私信发送用户的收藏列表"""
    user_id = update.effective_user.id
    async with db_transaction() as conn:
        favorites = await conn.fetch("SELECT favorite_username FROM favorites WHERE user_id = $1 ORDER BY favorite_username", user_id)
    
    if not favorites:
        text = "您的收藏夹是空的。"
    else:
        fav_list = "\n".join([f"- @{fav['favorite_username']}" for fav in favorites])
        text = "⭐ **我的收藏** ⭐\n\n" + fav_list

    try:
        # 尝试私信发送
        await context.bot.send_message(chat_id=user_id, text=text)
        if update.callback_query:
            await update.callback_query.answer("已将您的收藏列表私信发送给您。", show_alert=True)
        elif update.message:
            await update.message.reply_text("已将您的收藏列表私信发送给您。")
    except Exception as e:
        logger.warning(f"无法向用户 {user_id} 私信发送收藏夹: {e}")
        if update.callback_query:
            await update.callback_query.answer("无法私信给您，请先启动与我的对话。", show_alert=True)

async def handle_favorite_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理收藏/取消收藏按钮点击，并刷新信誉摘要视图"""
    query = update.callback_query
    action, nominee_username = query.data.split('_', 2)[1:]
    user_id = query.from_user.id

    async with db_transaction() as conn:
        if action == "add":
            await conn.execute(
                "INSERT INTO favorites (user_id, favorite_username) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                user_id, nominee_username
            )
            await query.answer("✅ 已加入收藏！", show_alert=False)
        elif action == "remove":
            await conn.execute(
                "DELETE FROM favorites WHERE user_id = $1 AND favorite_username = $2",
                user_id, nominee_username
            )
            await query.answer("🗑️ 已移出收藏。", show_alert=False)
    
    # --- 核心改造：操作完成后，刷新信誉摘要视图 ---
    summary = await get_reputation_summary(nominee_username, user_id)
    message_content = await build_summary_view(nominee_username, summary)
    await query.edit_message_text(**message_content)
