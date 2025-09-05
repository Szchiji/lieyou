import logging
import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from database import db_execute, db_fetch_all, db_fetchval, get_or_create_user

logger = logging.getLogger(__name__)

async def add_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int):
    """添加收藏，使用 pkid"""
    query = update.callback_query
    user = await get_or_create_user(user_id=query.from_user.id)
    
    if not user:
        await query.answer("❌ 无法识别您的身份，请稍后再试。", show_alert=True)
        return

    if user['pkid'] == target_user_pkid:
        await query.answer("❌ 你不能收藏自己。", show_alert=True)
        return

    try:
        await db_execute(
            "INSERT INTO favorites (user_pkid, target_user_pkid) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            user['pkid'], target_user_pkid
        )
        await query.answer("❤️ 已收藏！", show_alert=True)
    except Exception as e:
        logger.error(f"添加收藏失败: {e}", exc_info=True)
        await query.answer("❌ 添加收藏失败。", show_alert=True)

async def remove_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int):
    """移除收藏，使用 pkid"""
    query = update.callback_query
    user = await get_or_create_user(user_id=query.from_user.id)

    if not user:
        await query.answer("❌ 无法识别您的身份，请稍后再试。", show_alert=True)
        return

    try:
        await db_execute(
            "DELETE FROM favorites WHERE user_pkid = $1 AND target_user_pkid = $2",
            user['pkid'], target_user_pkid
        )
        await query.answer("💔 已取消收藏。", show_alert=True)
        # 刷新收藏列表（现在会私聊发送）
        await my_favorites_list(update, context, 1)
    except Exception as e:
        logger.error(f"移除收藏失败: {e}", exc_info=True)
        await query.answer("❌ 移除收藏失败。", show_alert=True)

async def my_favorites_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    """
    显示用户的收藏列表。
    无论从哪里触发，都将列表私聊发送给用户。
    """
    is_callback = update.callback_query is not None
    user = update.effective_user
    chat_type = update.effective_chat.type

    db_user = await get_or_create_user(user_id=user.id)
    if not db_user:
        err_msg = "❌ 无法获取您的用户信息，请稍后再试。"
        if is_callback:
            await update.callback_query.answer(err_msg, show_alert=True)
        else:
            await update.effective_message.reply_text(err_msg)
        return

    per_page = 10
    offset = (page - 1) * per_page
    
    try:
        favs = await db_fetch_all(
            """
            SELECT u.pkid, u.first_name, u.username FROM favorites f
            JOIN users u ON f.target_user_pkid = u.pkid
            WHERE f.user_pkid = $1 ORDER BY u.first_name, u.username
            LIMIT $2 OFFSET $3
            """,
            db_user['pkid'], per_page, offset
        )
        total_favs = await db_fetchval("SELECT COUNT(*) FROM favorites WHERE user_pkid = $1", db_user['pkid']) or 0
        total_pages = max(1, (total_favs + per_page - 1) // per_page)

        text = f"❤️ **我的收藏 (第 {page}/{total_pages} 页)**\n\n"
        keyboard_list = []
        if not favs:
            text += "你还没有收藏任何人。"
        else:
            for fav in favs:
                display_name = fav['first_name'] or (f"@{fav['username']}" if fav['username'] else f"用户 {fav['pkid']}")
                keyboard_list.append([
                    InlineKeyboardButton(display_name, callback_data=f"rep_card_query_{fav['pkid']}"),
                    InlineKeyboardButton("❌", callback_data=f"remove_favorite_{fav['pkid']}")
                ])
        
        nav_row = []
        if page > 1: nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"my_favorites_{page-1}"))
        if page < total_pages: nav_row.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"my_favorites_{page+1}"))
        if nav_row: keyboard_list.append(nav_row)

        # 无论如何，私聊中的返回按钮都应该是返回主菜单
        keyboard_list.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")])
        reply_markup = InlineKeyboardMarkup(keyboard_list)

        # --- 核心发送逻辑 ---
        try:
            # 如果是私聊中的按钮回调，则编辑消息
            if is_callback and chat_type == 'private':
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            # 否则，都发送新消息到私聊
            else:
                await context.bot.send_message(
                    chat_id=user.id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                # 如果是在群组里点的按钮，给一个提示
                if is_callback and chat_type != 'private':
                    await update.callback_query.answer("我已将你的收藏列表私聊发送给你。", show_alert=False)

        except Exception as e: # 特别是处理用户未与机器人开始私聊的情况
            logger.warning(f"无法向用户 {user.id} 发送私聊消息: {e}")
            if is_callback:
                await update.callback_query.answer("无法私聊给你，请先与我开始对话。", show_alert=True)
            elif update.effective_message:
                bot_username = (await context.bot.get_me()).username
                await update.effective_message.reply_text(
                    f"我无法私聊给你，请先点击这里 [@{bot_username}] 与我开始对话。",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("开始私聊", url=f"https://t.me/{bot_username}?start=start")]])
                )

    except Exception as e:
        logger.error(f"获取收藏列表失败 (user pkid: {db_user.get('pkid')}): {e}", exc_info=True)
        if is_callback:
            await update.callback_query.answer("❌ 获取收藏列表时出错。", show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text("❌ 获取收藏列表时出错。")
