import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from math import ceil

from database import get_or_create_user, db_execute, db_fetch_all, db_fetch_val
from .reputation import send_reputation_card
from .utils import membership_required

logger = logging.getLogger(__name__)

FAV_PAGE_SIZE = 5

@membership_required
async def my_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    """显示用户的收藏列表（分页）。"""
    query = update.callback_query
    user = query.from_user

    try:
        user_record = await get_or_create_user(user)
    except ValueError as e:
        await query.answer(f"❌ 操作失败: {e}", show_alert=True)
        return
    
    user_pkid = user_record['pkid']
    
    favorites = await db_fetch_all(
        """
        SELECT u.pkid, u.username 
        FROM favorites f
        JOIN users u ON f.target_user_pkid = u.pkid
        WHERE f.user_pkid = $1
        ORDER BY u.username
        """,
        user_pkid
    )

    if not favorites:
        text = "❤️ **我的收藏**\n\n您还没有收藏任何人。\n在查看声誉卡片时，可以点击“加入收藏”。"
        keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    total_pages = ceil(len(favorites) / FAV_PAGE_SIZE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * FAV_PAGE_SIZE
    favs_on_page = favorites[offset : offset + FAV_PAGE_SIZE]

    text = f"❤️ **我的收藏** (第 {page}/{total_pages} 页)\n\n以下是您收藏的用户列表："
    keyboard = []
    for fav in favs_on_page:
        keyboard.append([InlineKeyboardButton(f"@{fav['username']}", callback_data=f"back_to_rep_card_{fav['pkid']}_{fav['username']}")])

    pagination_row = []
    if page > 1: pagination_row.append(InlineKeyboardButton("⬅️", callback_data=f"my_favorites_{page-1}"))
    if page < total_pages: pagination_row.append(InlineKeyboardButton("➡️", callback_data=f"my_favorites_{page+1}"))
    if pagination_row: keyboard.append(pagination_row)
    
    keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


@membership_required
async def add_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE, target_pkid: int, target_username: str):
    """将用户添加到收藏夹。"""
    query = update.callback_query
    user = query.from_user

    try:
        user_record = await get_or_create_user(user)
    except ValueError as e:
        await query.answer(f"❌ 操作失败: {e}", show_alert=True)
        return
        
    user_pkid = user_record['pkid']

    try:
        await db_execute(
            "INSERT INTO favorites (user_pkid, target_user_pkid) VALUES ($1, $2) ON CONFLICT (user_pkid, target_user_pkid) DO NOTHING",
            user_pkid, target_pkid
        )
        await query.answer(f"✅ 已将 @{target_username} 加入收藏！", show_alert=True)
    except Exception as e:
        logger.error(f"添加收藏时数据库出错: {e}")
        await query.answer("❌ 数据库错误，请稍后再试。", show_alert=True)
        return

    # 刷新声誉卡片上的按钮
    target_user_record = {"pkid": target_pkid, "username": target_username}
    text_prefix = f"✅ 已将 @{target_username} 加入收藏！\n\n"
    await send_reputation_card(update, context, target_user_record, text_prefix)
    
    # 更新按钮为"移除收藏"
    recommends = await db_fetch_val("SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = $1 AND type = 'recommend'", target_pkid)
    blocks = await db_fetch_val("SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = $1 AND type = 'block'", target_pkid)
    favorited_by = await db_fetch_val("SELECT COUNT(*) FROM favorites WHERE target_user_pkid = $1", target_pkid)
    score = recommends - blocks

    text = f"声誉卡片: @{target_username}\n\n"
    text += f"👍 **推荐**: {recommends} 次\n"
    text += f"👎 **警告**: {blocks} 次\n"
    text += f"❤️ **收藏**: 被 {favorited_by} 人收藏\n"
    text += f"✨ **声望**: {score}\n"

    keyboard = [
        [
            InlineKeyboardButton(f"👍 推荐 ({recommends})", callback_data=f"vote_recommend_{target_pkid}_{target_username}"),
            InlineKeyboardButton(f"👎 警告 ({blocks})", callback_data=f"vote_block_{target_pkid}_{target_username}")
        ],
        [
            InlineKeyboardButton("💔 移除收藏", callback_data=f"remove_favorite_{target_pkid}_{target_username}"),
            InlineKeyboardButton("📊 查看统计", callback_data=f"stats_user_{target_pkid}_0_{target_username}")
        ]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


@membership_required
async def remove_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE, target_pkid: int, target_username: str):
    """从收藏夹移除用户。"""
    query = update.callback_query
    user = query.from_user

    try:
        user_record = await get_or_create_user(user)
    except ValueError as e:
        await query.answer(f"❌ 操作失败: {e}", show_alert=True)
        return
        
    user_pkid = user_record['pkid']

    try:
        await db_execute(
            "DELETE FROM favorites WHERE user_pkid = $1 AND target_user_pkid = $2",
            user_pkid, target_pkid
        )
        await query.answer(f"✅ 已从收藏夹移除 @{target_username}！", show_alert=True)
    except Exception as e:
        logger.error(f"移除收藏时数据库出错: {e}")
        await query.answer("❌ 数据库错误，请稍后再试。", show_alert=True)
        return
        
    # 刷新声誉卡片
    target_user_record = {"pkid": target_pkid, "username": target_username}
    await send_reputation_card(update, context, target_user_record)
