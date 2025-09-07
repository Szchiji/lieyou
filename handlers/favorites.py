import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from math import ceil
from telegram.constants import ParseMode

from database import get_or_create_user, db_execute, db_fetch_all
from handlers.reputation import send_reputation_card
from handlers.utils import membership_required # <-- 导入我们的检查器

logger = logging.getLogger(__name__)

PAGE_SIZE = 5

@membership_required # <-- 贴上标签
async def add_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, origin: str):
    """将一个目标添加到用户的收藏夹。"""
    query = update.callback_query
    
    try:
        from_user = await get_or_create_user(query.from_user)
    except ValueError as e:
        await query.answer(f"❌ 操作失败: {e}", show_alert=True)
        return

    if from_user['pkid'] == target_user_pkid:
        await query.answer("🤔 你不能收藏自己哦。", show_alert=True)
        return

    try:
        await db_execute(
            "INSERT INTO favorites (user_pkid, target_user_pkid) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            from_user['pkid'], target_user_pkid
        )
        await query.answer("❤️ 已收藏！", show_alert=True)
    except Exception as e:
        logger.error(f"添加收藏失败: {e}", exc_info=True)
        await query.answer("❌ 添加收藏失败。", show_alert=True)

    await send_reputation_card(update, context, target_user_pkid, origin)


@membership_required # <-- 贴上标签
async def remove_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, origin: str):
    """从用户的收藏夹中移除一个目标。"""
    query = update.callback_query

    try:
        from_user = await get_or_create_user(query.from_user)
    except ValueError as e:
        await query.answer(f"❌ 操作失败: {e}", show_alert=True)
        return

    try:
        await db_execute(
            "DELETE FROM favorites WHERE user_pkid = $1 AND target_user_pkid = $2",
            from_user['pkid'], target_user_pkid
        )
        await query.answer("💔 已取消收藏。", show_alert=True)
    except Exception as e:
        logger.error(f"移除收藏失败: {e}", exc_info=True)
        await query.answer("❌ 取消收藏失败。", show_alert=True)

    if origin and origin.startswith("fav_"):
        page = int(origin.split('_')[1])
        await my_favorites(update, context, page)
    else: 
        await send_reputation_card(update, context, target_user_pkid, origin)


@membership_required # <-- 贴上标签
async def my_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    """显示用户的收藏列表。"""
    query = update.callback_query
    
    try:
        user = await get_or_create_user(query.from_user)
    except ValueError as e:
        await query.answer(f"❌ 操作失败: {e}", show_alert=True)
        await query.message.edit_text(f"❌ 操作失败: {e}\n\n你需要设置一个Telegram用户名才能使用收藏功能。")
        return

    favorites = await db_fetch_all("""
        SELECT u.pkid, u.username
        FROM favorites f
        JOIN users u ON f.target_user_pkid = u.pkid
        WHERE f.user_pkid = $1
        ORDER BY f.created_at DESC
    """, user['pkid'])
    
    total_count = len(favorites)
    total_pages = ceil(total_count / PAGE_SIZE) if total_count > 0 else 1
    page = max(1, min(page, total_pages))
    offset = (page - 1) * PAGE_SIZE
    
    favorites_on_page = favorites[offset : offset + PAGE_SIZE]
    
    text = f"**❤️ 我的收藏** \\(第 {page}/{total_pages} 页\\)\n\n"
    
    if not favorites_on_page:
        text += "_你还没有收藏任何目标_\\.\n\n你可以通过声誉卡片上的“❤️ 添加收藏”按钮来收藏。"
    
    keyboard = []
    for fav in favorites_on_page:
        origin = f"fav_{page}"
        safe_username = fav['username'].replace('_', '\\_').replace('*', '\\*')
        keyboard.append([
            InlineKeyboardButton(f"@{safe_username}", callback_data=f"back_to_rep_card_{fav['pkid']}_{origin}")
        ])
        
    pagination = []
    if page > 1:
        pagination.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"my_favorites_{page-1}"))
    if page < total_pages:
        pagination.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"my_favorites_{page+1}"))
    if pagination:
        keyboard.append(pagination)
        
    keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)
