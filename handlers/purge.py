import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_fetch_all, db_execute, db_transaction

logger = logging.getLogger(__name__)

async def show_purge_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示抹除室菜单"""
    callback_query = update.callback_query
    await callback_query.answer()
    
    # 创建抹除室菜单
    keyboard = [
        [InlineKeyboardButton("🧹 清除我的所有评价", callback_data="purge_all_votes")],
        [InlineKeyboardButton("🚫 清除我的负面评价", callback_data="purge_negative_votes")],
        [InlineKeyboardButton("« 返回", callback_data="back_to_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await callback_query.edit_message_text(
        text="🧹 **抹除室**\n\n"
             "在这里，你可以清除你对他人的评价记录。\n\n"
             "⚠️ **警告**: 此操作不可逆，请谨慎选择！",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def handle_purge_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理抹除室按钮操作"""
    callback_query = update.callback_query
    user_id = update.effective_user.id
    data = callback_query.data
    
    await callback_query.answer("处理中...")
    
    if data == "purge_all_votes":
        result = await purge_votes(user_id, all_votes=True)
        if result > 0:
            message = f"✅ 成功清除了你的 {result} 条评价记录"
        else:
            message = "ℹ️ 没有找到可清除的评价记录"
    
    elif data == "purge_negative_votes":
        result = await purge_votes(user_id, all_votes=False)
        if result > 0:
            message = f"✅ 成功清除了你的 {result} 条负面评价记录"
        else:
            message = "ℹ️ 没有找到可清除的负面评价记录"
    else:
        message = "❌ 未知的操作"
    
    # 创建返回按钮
    keyboard = [[InlineKeyboardButton("« 返回抹除室", callback_data="show_purge_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await callback_query.edit_message_text(
        text=f"🧹 **抹除室结果**\n\n{message}",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def purge_votes(user_id, all_votes=True):
    """清除用户的评价记录
    
    Args:
        user_id (int): 用户ID
        all_votes (bool): True清除所有评价，False只清除负面评价
    
    Returns:
        int: 清除的评价数量
    """
    try:
        async with db_transaction() as conn:
            if all_votes:
                # 清除所有评价
                query = """
                DELETE FROM reputation
                WHERE voter_id = $1
                RETURNING id
                """
                results = await conn.fetch(query, user_id)
            else:
                # 只清除负面评价
                query = """
                DELETE FROM reputation
                WHERE voter_id = $1 AND is_positive = FALSE
                RETURNING id
                """
                results = await conn.fetch(query, user_id)
            
            return len(results)
    except Exception as e:
        logger.error(f"清除评价记录时发生错误: {e}", exc_info=True)
        return 0
