import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import db_execute, db_fetch_all, db_fetchval
from .reputation import build_reputation_card_data, format_reputation_card
from .utils import schedule_message_deletion

logger = logging.getLogger(__name__)

ITEMS_PER_PAGE = 5

async def add_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int):
    """添加用户到收藏夹"""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        await db_execute(
            "INSERT INTO favorites (user_id, target_user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            user_id, target_user_id
        )
        await query.answer("❤️ 已添加到收藏夹！", show_alert=True)
        
        # 刷新声誉卡片以更新按钮状态
        card_data = await build_reputation_card_data(target_user_id)
        if card_data:
            text, keyboard = format_reputation_card(card_data, is_favorite=True)
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"添加收藏失败 (user: {user_id}, target: {target_user_id}): {e}")
        await query.answer("❌ 操作失败。", show_alert=True)

async def remove_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int):
    """从收藏夹移除用户"""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        await db_execute(
            "DELETE FROM favorites WHERE user_id = $1 AND target_user_id = $2",
            user_id, target_user_id
        )
        await query.answer("🤍 已从收藏夹移除。", show_alert=True)
        
        # 刷新声誉卡片以更新按钮状态
        card_data = await build_reputation_card_data(target_user_id)
        if card_data:
            text, keyboard = format_reputation_card(card_data, is_favorite=False)
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"移除收藏失败 (user: {user_id}, target: {target_user_id}): {e}")
        await query.answer("❌ 操作失败。", show_alert=True)

async def my_favorites_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
    """显示用户的收藏列表"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    offset = (page - 1) * ITEMS_PER_PAGE

    try:
        favorites = await db_fetch_all(
            """
            SELECT u.id, u.first_name, u.username
            FROM favorites f
            JOIN users u ON f.target_user_id = u.id
            WHERE f.user_id = $1
            ORDER BY u.first_name, u.username
            LIMIT $2 OFFSET $3
            """,
            user_id, ITEMS_PER_PAGE, offset
        )
        
        total_count = await db_fetchval("SELECT COUNT(*) FROM favorites WHERE user_id = $1", user_id) or 0
        total_pages = (total_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE or 1

        if not favorites and page == 1:
            message = "你的收藏夹是空的哦。"
            keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")]]
        else:
            message = f"❤️ **我的收藏** (第 {page}/{total_pages} 页)\n\n点击用户名可直接查看对方声誉："
            keyboard = []
            for fav in favorites:
                display_name = fav['first_name'] or (f"@{fav['username']}" if fav['username'] else f"用户{fav['id']}")
                keyboard.append([InlineKeyboardButton(f"👤 {display_name}", callback_data=f"rep_card_query_{fav['id']}")])
            
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"my_favorites_{page-1}"))
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"my_favorites_{page+1}"))
            
            if nav_buttons:
                keyboard.append(nav_buttons)
            
            keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")])

        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        logger.error(f"获取收藏列表失败 (user: {user_id}): {e}")
        await query.edit_message_text("❌ 获取收藏列表时出错。")
