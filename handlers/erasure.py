import logging
from typing import Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import db_transaction, update_user_activity, db_execute, db_fetchval

logger = logging.getLogger(__name__)

async def handle_erasure_functions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理抹除室相关功能的统一入口"""
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    
    await update_user_activity(user_id, update.effective_user.username, update.effective_user.first_name)
    
    if data == "erasure_menu":
        await show_erasure_menu(update, context)
    elif data == "erasure_self_data":
        await confirm_self_data_erasure(update, context)
    elif data == "erasure_given_votes":
        await confirm_given_votes_erasure(update, context)
    elif data == "erasure_received_votes":
        await confirm_received_votes_erasure(update, context)
    elif data.startswith("erasure_confirm_"):
        action = data.replace("erasure_confirm_", "")
        await execute_erasure(update, context, action)

async def show_erasure_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示抹除室主菜单"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    # 获取用户数据统计
    try:
        async with db_transaction() as conn:
            given_votes = await conn.fetchval("SELECT COUNT(*) FROM reputations WHERE voter_id = $1", user_id) or 0
            received_votes = await conn.fetchval("SELECT COUNT(*) FROM reputations WHERE target_id = $1", user_id) or 0
            favorites_count = await conn.fetchval("SELECT COUNT(*) FROM favorites WHERE user_id = $1", user_id) or 0
    except Exception as e:
        logger.error(f"获取用户统计失败: {e}")
        given_votes = received_votes = favorites_count = 0
    
    message = (
        "🔥 **抹除室** - 数据清理中心\n\n"
        "⚠️ **警告**: 以下操作不可撤销！\n\n"
        f"📊 **您的数据统计**:\n"
        f"• 给出的评价: {given_votes} 条\n"
        f"• 收到的评价: {received_votes} 条\n"
        f"• 收藏的用户: {favorites_count} 个\n\n"
        "选择要清理的数据类型:"
    )
    
    keyboard = [
        [InlineKeyboardButton("🗑️ 清除个人资料", callback_data="erasure_self_data")],
        [InlineKeyboardButton("📤 清除给出的评价", callback_data="erasure_given_votes")],
        [InlineKeyboardButton("📥 清除收到的评价", callback_data="erasure_received_votes")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def confirm_self_data_erasure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """确认个人数据完全抹除"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    # 获取详细统计
    try:
        async with db_transaction() as conn:
            given_votes = await conn.fetchval("SELECT COUNT(*) FROM reputations WHERE voter_id = $1", user_id) or 0
            received_votes = await conn.fetchval("SELECT COUNT(*) FROM reputations WHERE target_id = $1", user_id) or 0
            favorites_given = await conn.fetchval("SELECT COUNT(*) FROM favorites WHERE user_id = $1", user_id) or 0
            favorites_received = await conn.fetchval("SELECT COUNT(*) FROM favorites WHERE target_id = $1", user_id) or 0
    except Exception as e:
        logger.error(f"获取统计失败: {e}")
        given_votes = received_votes = favorites_given = favorites_received = 0
    
    message = (
        f"🗑️ **完全数据清理确认**\n\n"
        f"此操作将彻底清除:\n"
        f"• 您的用户资料和身份信息\n"
        f"• 您给出的 **{given_votes}** 条评价\n"
        f"• 您收到的 **{received_votes}** 条评价\n"
        f"• 您收藏的 **{favorites_given}** 个用户\n"
        f"• 被其他人收藏您的 **{favorites_received}** 条记录\n"
        f"• 所有与您相关的系统记录\n\n"
        f"⚠️ **此操作彻底不可撤销！您将从系统中完全消失！**\n\n"
        f"🚪 执行后您需要重新开始使用机器人。"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔴 确认彻底清除", callback_data="erasure_confirm_self_data")],
        [InlineKeyboardButton("❌ 我再想想", callback_data="erasure_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def confirm_given_votes_erasure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """确认清除给出的评价"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    # 获取统计
    given_votes = await db_fetchval("SELECT COUNT(*) FROM reputations WHERE voter_id = $1", user_id) or 0
    
    if given_votes == 0:
        await query.edit_message_text(
            "ℹ️ **没有需要清除的数据**\n\n您还没有给任何人评价过。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回", callback_data="erasure_menu")
            ]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    message = (
        f"📤 **清除给出评价确认**\n\n"
        f"此操作将清除您给出的 **{given_votes}** 条评价。\n\n"
        f"包括:\n"
        f"• 所有好评和差评记录\n"
        f"• 评价时选择的标签\n"
        f"• 评价留言（如有）\n\n"
        f"⚠️ **此操作不可撤销！**\n"
        f"被您评价的用户将失去来自您的声誉分。"
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ 确认清除", callback_data="erasure_confirm_given_votes")],
        [InlineKeyboardButton("❌ 取消", callback_data="erasure_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def confirm_received_votes_erasure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """确认清除收到的评价"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    # 获取统计
    received_votes = await db_fetchval("SELECT COUNT(*) FROM reputations WHERE target_id = $1", user_id) or 0
    
    if received_votes == 0:
        await query.edit_message_text(
            "ℹ️ **没有需要清除的数据**\n\n您还没有收到任何评价。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回", callback_data="erasure_menu")
            ]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    message = (
        f"📥 **清除收到评价确认**\n\n"
        f"此操作将清除您收到的 **{received_votes}** 条评价。\n\n"
        f"影响:\n"
        f"• 您将从所有排行榜中消失\n"
        f"• 您的声誉分将重置为0\n"
        f"• 其他用户将无法查看您的声誉历史\n"
        f"• 所有收藏您的记录也会被清除\n\n"
        f"⚠️ **此操作不可撤销！**\n"
        f"您需要重新积累声誉。"
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ 确认清除", callback_data="erasure_confirm_received_votes")],
        [InlineKeyboardButton("❌ 取消", callback_data="erasure_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def execute_erasure(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    """执行抹除操作"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    try:
        async with db_transaction() as conn:
            if action == "self_data":
                # 完全清除用户数据
                # 1. 清除给出的评价
                given_count = await conn.fetchval("SELECT COUNT(*) FROM reputations WHERE voter_id = $1", user_id) or 0
                await conn.execute("DELETE FROM reputations WHERE voter_id = $1", user_id)
                
                # 2. 清除收到的评价
                received_count = await conn.fetchval("SELECT COUNT(*) FROM reputations WHERE target_id = $1", user_id) or 0
                await conn.execute("DELETE FROM reputations WHERE target_id = $1", user_id)
                
                # 3. 清除收藏记录（给出和收到）
                fav_given = await conn.fetchval("SELECT COUNT(*) FROM favorites WHERE user_id = $1", user_id) or 0
                fav_received = await conn.fetchval("SELECT COUNT(*) FROM favorites WHERE target_id = $1", user_id) or 0
                await conn.execute("DELETE FROM favorites WHERE user_id = $1 OR target_id = $1", user_id)
                
                # 4. 清除用户资料
                await conn.execute("DELETE FROM users WHERE id = $1", user_id)
                
                # 5. 记录抹除操作
                await conn.execute(
                    "INSERT INTO erasure_records (user_id, type) VALUES ($1, 'self_data')",
                    user_id
                )
                
                message = (
                    "🗑️ **完全数据清除完成**\n\n"
                    f"已清除数据:\n"
                    f"• 给出评价: {given_count} 条\n"
                    f"• 收到评价: {received_count} 条\n"
                    f"• 收藏记录: {fav_given + fav_received} 条\n"
                    f"• 个人资料: 已删除\n\n"
                    "🌟 您已从神谕系统中完全消失。\n"
                    "如需重新使用，请发送 /start 重新开始。"
                )
                
            elif action == "given_votes":
                # 只清除给出的评价
                count = await conn.fetchval("SELECT COUNT(*) FROM reputations WHERE voter_id = $1", user_id) or 0
                await conn.execute("DELETE FROM reputations WHERE voter_id = $1", user_id)
                await conn.execute(
                    "INSERT INTO erasure_records (user_id, type) VALUES ($1, 'given_votes')",
                    user_id
                )
                
                message = (
                    "📤 **给出评价已清除**\n\n"
                    f"已清除 **{count}** 条您给出的评价。\n\n"
                    "✨ 您现在可以重新开始评价他人。"
                )
                
            elif action == "received_votes":
                # 只清除收到的评价
                vote_count = await conn.fetchval("SELECT COUNT(*) FROM reputations WHERE target_id = $1", user_id) or 0
                fav_count = await conn.fetchval("SELECT COUNT(*) FROM favorites WHERE target_id = $1", user_id) or 0
                
                await conn.execute("DELETE FROM reputations WHERE target_id = $1", user_id)
                await conn.execute("DELETE FROM favorites WHERE target_id = $1", user_id)
                await conn.execute(
                    "INSERT INTO erasure_records (user_id, type) VALUES ($1, 'received_votes')",
                    user_id
                )
                
                message = (
                    "📥 **收到评价已清除**\n\n"
                    f"已清除:\n"
                    f"• 收到评价: **{vote_count}** 条\n"
                    f"• 收藏记录: **{fav_count}** 条\n\n"
                    "✨ 您已从排行榜中消失，声誉重新开始。"
                )
        
        # 清除相关缓存
        try:
            from handlers.leaderboard import clear_leaderboard_cache
            clear_leaderboard_cache()
        except ImportError:
            logger.warning("无法导入排行榜缓存清理函数")
        
        # 构建返回按钮
        if action == "self_data":
            # 完全清除后，只能返回开始
            keyboard = [[InlineKeyboardButton("🔄 重新开始", callback_data="back_to_help")]]
        else:
            keyboard = [
                [InlineKeyboardButton("🔙 返回抹除室", callback_data="erasure_menu")],
                [InlineKeyboardButton("🏠 返回主菜单", callback_data="back_to_help")]
            ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message, 
            reply_markup=reply_markup, 
            parse_mode=ParseMode.MARKDOWN
        )
        
        logger.info(f"用户 {user_id} 执行了抹除操作: {action}")
        
    except Exception as e:
        logger.error(f"执行抹除操作失败: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ **抹除操作失败**\n\n"
            "系统出现错误，请稍后再试。\n"
            "如果问题持续，请联系管理员。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回抹除室", callback_data="erasure_menu"),
                InlineKeyboardButton("🏠 返回主菜单", callback_data="back_to_help")
            ]]),
            parse_mode=ParseMode.MARKDOWN
        )
