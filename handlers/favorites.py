import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from math import ceil

from database import get_or_create_user, db_execute, db_fetch_all, db_fetch_one
from .reputation import send_reputation_card

logger = logging.getLogger(__name__)

PAGE_SIZE = 5

async def add_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, origin: str):
    query = update.callback_query
    user = await get_or_create_user(user_id=query.from_user.id)
    
    try:
        await db_execute("INSERT INTO favorites (user_pkid, target_user_pkid) VALUES ($1, $2) ON CONFLICT DO NOTHING", user['pkid'], target_user_pkid)
        await query.answer("❤️ 已收藏！")
    except Exception as e:
        logger.error(f"添加收藏失败: {e}", exc_info=True)
        await query.answer("❌ 添加收藏失败。", show_alert=True)
        
    await send_reputation_card(update, context, target_user_pkid, origin)

async def remove_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, origin: str):
    query = update.callback_query
    user = await get_or_create_user(user_id=query.from_user.id)

    try:
        await db_execute("DELETE FROM favorites WHERE user_pkid = $1 AND target_user_pkid = $2", user['pkid'], target_user_pkid)
        await query.answer("💔 已取消收藏。")
    except Exception as e:
        logger.error(f"取消收藏失败: {e}", exc_info=True)
        await query.answer("❌ 取消收藏失败。", show_alert=True)
        
    # 如果是从收藏列表页过来的，刷新收藏列表
    if origin and origin.startswith("fav_"):
        page = int(origin.split('_')[1])
        await my_favorites(update, context, page)
    else: # 否则，刷新声誉卡片
        await send_reputation_card(update, context, target_user_pkid, origin)

async def my_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    query = update.callback_query
    user = await get_or_create_user(user_id=query.from_user.id)

    total_fav_rec = await db_fetch_one("SELECT COUNT(*) as count FROM favorites WHERE user_pkid = $1", user['pkid'])
    total_count = total_fav_rec.get('count', 0)
    total_pages = ceil(total_count / PAGE_SIZE) if total_count > 0 else 1
    page = max(1, min(page, total_pages))
    offset = (page - 1) * PAGE_SIZE

    fav_users = await db_fetch_all("""
        SELECT u.pkid, u.first_name, u.username
        FROM favorites f
        JOIN users u ON f.target_user_pkid = u.pkid
        WHERE f.user_pkid = $1
        ORDER BY f.created_at DESC
        LIMIT $2 OFFSET $3
    """, user['pkid'], PAGE_SIZE, offset)

    text = f"❤️ **我的收藏** (共 {total_count} 个)\n\n"
    keyboard = []
    if not fav_users:
        text += "_你还没有收藏任何人。_"
    else:
        for fav_user in fav_users:
            display_name = f"@{fav_user['username']}" if fav_user['username'] else fav_user['first_name']
            # origin 'fav_{page}' 用于告知声誉卡片，返回时应回到收藏列表的哪一页
            keyboard.append([InlineKeyboardButton(display_name, callback_data=f"back_to_rep_card_{fav_user['pkid']}_fav_{page}")])

    pagination = []
    if page > 1: pagination.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"my_favorites_{page-1}"))
    if page < total_pages: pagination.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"my_favorites_{page+1}"))
    if pagination: keyboard.append(pagination)
    
    keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
