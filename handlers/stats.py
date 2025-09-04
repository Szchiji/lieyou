import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import get_system_stats, update_user_activity
from datetime import datetime

logger = logging.getLogger(__name__)

async def show_system_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示系统统计数据"""
    user_id = update.effective_user.id
    
    # 更新用户活动记录
    await update_user_activity(user_id, update.effective_user.username)
    
    # 获取系统统计数据
    stats = await get_system_stats()
    
    # 当前时间
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 构建统计信息文本
    text_parts = [
        "📊 <b>神谕数据</b>\n" + ("-"*20),
        f"\n⏰ <b>时间印记:</b> {current_time}",
        f"\n👥 <b>用户数据:</b>",
        f"  - 总用户数: {stats['total_users']} 位求道者",
        f"  - 总档案数: {stats['total_profiles']} 份神谕之卷",
        f"\n⚖️ <b>审判数据:</b>",
        f"  - 累计审判: {stats['total_votes']} 次",
        f"  - 今日审判: {stats['today_votes']} 次",
        f"\n📜 <b>箴言数据:</b>",
        f"  - 赞誉箴言: {stats['recommend_tags']} 种",
        f"  - 警示箴言: {stats['block_tags']} 种",
    ]
    
    # 如果有最活跃用户，添加到统计中
    if stats.get('most_active_user'):
        text_parts.append(f"\n🌟 <b>最活跃存在:</b> @{stats['most_active_user']}")
    
    text = "\n".join(text_parts)
    
    # 创建按钮
    keyboard = [
        [InlineKeyboardButton("🔄 刷新数据", callback_data="show_system_stats")],
        [InlineKeyboardButton("🌍 返回凡界", callback_data="back_to_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # 发送或更新消息
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
