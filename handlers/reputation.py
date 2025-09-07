import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import get_or_create_user, get_or_create_target, db_fetch_all, db_fetch_one, db_execute, db_fetch_val
from .utils import membership_required
from . import statistics as statistics_handlers

logger = logging.getLogger(__name__)

async def send_reputation_card(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_record: dict, text_prefix: str = ""):
    """发送一个用户的声誉卡片，包含评价和统计信息。"""
    target_pkid = target_user_record['pkid']
    target_username = target_user_record['username']
    
    # 获取统计数据
    recommends = await db_fetch_val("SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = $1 AND type = 'recommend'", target_pkid)
    blocks = await db_fetch_val("SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = $1 AND type = 'block'", target_pkid)
    favorited_by = await db_fetch_val("SELECT COUNT(*) FROM favorites WHERE target_user_pkid = $1", target_pkid)
    score = recommends - blocks

    # 构建文本
    text = f"{text_prefix}声誉卡片: @{target_username}\n\n"
    text += f"👍 **推荐**: {recommends} 次\n"
    text += f"👎 **警告**: {blocks} 次\n"
    text += f"❤️ **收藏**: 被 {favorited_by} 人收藏\n"
    text += f"✨ **声望**: {score}\n"

    # 构建按钮
    keyboard = [
        [
            InlineKeyboardButton(f"👍 推荐 ({recommends})", callback_data=f"vote_recommend_{target_pkid}_{target_username}"),
            InlineKeyboardButton(f"👎 警告 ({blocks})", callback_data=f"vote_block_{target_pkid}_{target_username}")
        ],
        [
            InlineKeyboardButton("❤️ 加入收藏", callback_data=f"add_favorite_{target_pkid}_{target_username}"),
            InlineKeyboardButton("📊 查看统计", callback_data=f"stats_user_{target_pkid}_0_{target_username}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

@membership_required
async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理包含@username的文本消息。"""
    message_text = update.message.text
    # 匹配 @username 和可选的评价词
    match = re.search(r'@(\w+)\s*(推荐|警告)?', message_text)
    if not match:
        return

    target_username = match.group(1).lower()
    action = match.group(2)
    
    user = update.effective_user
    
    try:
        user_record = await get_or_create_user(user)
        target_user_record = await get_or_create_target(target_username)
    except ValueError as e:
        await update.message.reply_text(f"❌ 操作失败: {e}")
        return
    except Exception as e:
        logger.error(f"处理声誉查询时数据库出错: {e}")
        await update.message.reply_text("❌ 数据库错误，请稍后再试。")
        return

    if not action:
        # 如果没有指定动作，只显示声誉卡片
        await send_reputation_card(update, context, target_user_record)
    else:
        # 如果指定了动作，直接弹出标签选择菜单
        vote_type = 'recommend' if action == '推荐' else 'block'
        await vote_menu(update, context, target_user_record['pkid'], vote_type, target_user_record['username'])


async def vote_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, target_pkid: int, vote_type: str, target_username: str):
    """显示用于评价的标签列表。"""
    tags = await db_fetch_all("SELECT pkid, name FROM tags WHERE type = $1 ORDER BY name", vote_type)
    
    action_text = "推荐" if vote_type == 'recommend' else "警告"
    text = f"你正在为 @{target_username} 添加“{action_text}”评价。\n请选择一个标签："

    keyboard = []
    row = []
    for tag in tags:
        row.append(InlineKeyboardButton(tag['name'], callback_data=f"process_vote_{target_pkid}_{tag['pkid']}_{target_username}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("🔙 返回声誉卡片", callback_data=f"back_to_rep_card_{target_pkid}_{target_username}")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        # From handle_query directly
        await update.message.reply_text(text, reply_markup=reply_markup)


async def process_vote(update: Update, context: ContextTypes.DEFAULT_TYPE, target_pkid: int, tag_pkid: int, target_username: str):
    """处理用户的评价投票。"""
    query = update.callback_query
    user = query.from_user

    try:
        user_record = await get_or_create_user(user)
    except ValueError as e:
        await query.answer(f"❌ 操作失败: {e}", show_alert=True)
        return
        
    tag_info = await db_fetch_one("SELECT name, type FROM tags WHERE pkid = $1", tag_pkid)
    if not tag_info:
        await query.answer("❌ 标签不存在！", show_alert=True)
        return
        
    vote_type = tag_info['type']
    
    try:
        # 使用 ON CONFLICT 来处理重复投票，实现 "覆盖" 逻辑
        await db_execute(
            """
            INSERT INTO evaluations (user_pkid, target_user_pkid, tag_pkid, type)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_pkid, target_user_pkid, tag_pkid) DO NOTHING;
            """,
            user_record['pkid'], target_pkid, tag_pkid, vote_type
        )
        action_text = "推荐" if vote_type == 'recommend' else "警告"
        await query.answer(f"✅ 已为 @{target_username} 添加“{tag_info['name']}”{action_text}评价！", show_alert=True)

    except Exception as e:
        logger.error(f"处理投票时数据库出错: {e}")
        await query.answer("❌ 数据库错误，请稍后再试。", show_alert=True)
        return

    # 刷新声誉卡片
    target_user_record = {"pkid": target_pkid, "username": target_username}
    await send_reputation_card(update, context, target_user_record)


async def back_to_rep_card(update: Update, context: ContextTypes.DEFAULT_TYPE, target_pkid: int, target_username: str):
    """回调函数，用于从其他菜单返回声誉卡片。"""
    target_user_record = {"pkid": target_pkid, "username": target_username}
    await send_reputation_card(update, context, target_user_record)
