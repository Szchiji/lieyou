import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from database import (
    db_transaction, update_user_activity, get_user_by_username,
    get_tags_by_type, add_nomination, get_reputation_summary,
    get_reputation_details, get_reputation_voters, get_tag_by_id,
    is_favorite, toggle_favorite, get_user_name
)

logger = logging.getLogger(__name__)

async def handle_nomination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理用户提名"""
    message = update.message
    
    # 从消息中提取@的用户名
    username = None
    match = None
    
    if message.text.startswith("查询"):
        match = context.matches[0]
        if match.group(1):
            username = match.group(1)
        elif match.group(2):
            username = match.group(2)
    else:
        match = context.matches[0]
        if match.group(1):
            username = match.group(1)
    
    if not username:
        await message.reply_text("未能识别用户名")
        return
    
    # 更新调用者的活动时间
    caller_id = update.effective_user.id
    caller_username = update.effective_user.username
    await update_user_activity(caller_id, caller_username)
    
    # 获取被提名用户
    nominee = await get_user_by_username(username)
    if not nominee:
        await message.reply_text(f"未找到用户 @{username}")
        return
    
    nominee_id = nominee['id']
    
    # 如果是查询自己
    if nominee_id == caller_id:
        await message.reply_text("自己评价自己？还是先听听别人怎么说吧！")
        return
    
    # 获取声誉摘要
    rep_summary = await get_reputation_summary(nominee_id)
    
    # 构建回复消息
    is_faved = await is_favorite(caller_id, nominee_id)
    text = format_reputation_summary(username, rep_summary, is_faved)
    
    # 创建按钮
    keyboard = [
        [
            InlineKeyboardButton("👍 好评", callback_data=f"vote_good_{nominee_id}"),
            InlineKeyboardButton("👎 差评", callback_data=f"vote_bad_{nominee_id}")
        ],
        [
            InlineKeyboardButton("📊 详情", callback_data=f"rep_detail_{nominee_id}"),
            InlineKeyboardButton("❤️ 收藏" if not is_faved else "💔 取消收藏", 
                               callback_data=f"query_fav_{nominee_id}")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def handle_username_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """在私聊中处理用户名查询"""
    message = update.message
    
    match = context.matches[0]
    username = match.group(1)
    if not username:
        await message.reply_text("未能识别用户名")
        return
    
    # 更新调用者的活动时间
    caller_id = update.effective_user.id
    caller_username = update.effective_user.username
    await update_user_activity(caller_id, caller_username)
    
    # 获取被提名用户
    nominee = await get_user_by_username(username)
    if not nominee:
        await message.reply_text(f"未找到用户 @{username}")
        return
    
    nominee_id = nominee['id']
    
    # 如果是查询自己
    if nominee_id == caller_id:
        await message.reply_text("自己评价自己？还是先听听别人怎么说吧！")
        return
    
    # 获取声誉摘要
    rep_summary = await get_reputation_summary(nominee_id)
    
    # 构建回复消息
    is_faved = await is_favorite(caller_id, nominee_id)
    text = format_reputation_summary(username, rep_summary, is_faved)
    
    # 创建按钮
    keyboard = [
        [
            InlineKeyboardButton("👍 好评", callback_data=f"vote_good_{nominee_id}"),
            InlineKeyboardButton("👎 差评", callback_data=f"vote_bad_{nominee_id}")
        ],
        [
            InlineKeyboardButton("📊 详情", callback_data=f"rep_detail_{nominee_id}"),
            InlineKeyboardButton("❤️ 收藏" if not is_faved else "💔 取消收藏", 
                               callback_data=f"query_fav_{nominee_id}")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

def format_reputation_summary(username: str, rep_summary: Dict, is_faved: bool = False) -> str:
    """格式化声誉摘要信息"""
    positive = rep_summary.get('positive_count', 0)
    negative = rep_summary.get('negative_count', 0)
    voter_count = rep_summary.get('voter_count', 0)
    top_tags = rep_summary.get('top_tags', [])
    
    # 不使用特殊字体，使用普通文本显示用户名
    header = f"🔮 **用户 @{username}** 的神谕卷轴"
    if is_faved:
        header += " ❤️"
    
    text_parts = [header, ""]
    
    if positive == 0 and negative == 0:
        text_parts.append("📜 此人尚无神谕记录")
    else:
        # 添加好评/差评比例
        total = positive + negative
        if total > 0:
            positive_percent = int(positive / total * 100)
            reputation_bar = generate_reputation_bar(positive_percent)
            text_parts.append(f"📊 **声誉比例**: {positive_percent}% 好评")
            text_parts.append(f"{reputation_bar}")
        
        text_parts.append(f"👥 **点评人数**: {voter_count} 位")
        
        # 添加最常见标签
        if top_tags:
            text_parts.append("\n🏷 **常见标签**:")
            for tag in top_tags:
                emoji = "👍" if tag['tag_type'] == 'recommend' else "👎"
                count = tag['count']
                content = tag['content']
                text_parts.append(f"{emoji} {content} ({count})")
    
    return "\n".join(text_parts)

def generate_reputation_bar(positive_percent: int) -> str:
    """生成可视化的声誉条"""
    total_blocks = 10
    positive_blocks = round(positive_percent / 100 * total_blocks)
    negative_blocks = total_blocks - positive_blocks
    
    bar = "🟩" * positive_blocks + "🟥" * negative_blocks
    return bar

async def show_reputation_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示用户声誉摘要"""
    query = update.callback_query
    data = query.data
    nominee_id = int(data.split('_')[-1])
    
    caller_id = update.effective_user.id
    await update_user_activity(caller_id)
    
    # 获取被提名用户名
    username = await get_user_name(nominee_id)
    
    # 获取声誉摘要
    rep_summary = await get_reputation_summary(nominee_id)
    
    # 构建回复消息
    is_faved = await is_favorite(caller_id, nominee_id)
    text = format_reputation_summary(username, rep_summary, is_faved)
    
    # 创建按钮
    keyboard = [
        [
            InlineKeyboardButton("👍 好评", callback_data=f"vote_good_{nominee_id}"),
            InlineKeyboardButton("👎 差评", callback_data=f"vote_bad_{nominee_id}")
        ],
        [
            InlineKeyboardButton("📊 详情", callback_data=f"rep_detail_{nominee_id}"),
            InlineKeyboardButton("❤️ 收藏" if not is_faved else "💔 取消收藏", 
                               callback_data=f"query_fav_{nominee_id}")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def show_reputation_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示用户声誉详情"""
    query = update.callback_query
    data = query.data
    nominee_id = int(data.split('_')[-1])
    
    caller_id = update.effective_user.id
    await update_user_activity(caller_id)
    
    # 获取被提名用户名
    username = await get_user_name(nominee_id)
    
    # 获取声誉详情
    rep_details = await get_reputation_details(nominee_id)
    
    # 构建回复消息
    text = format_reputation_details(username, rep_details)
    
    # 创建按钮
    keyboard = []
    
    # 推荐标签投票者按钮
    recommend_tags = rep_details.get('recommend_tags', [])
    if recommend_tags:
        keyboard.append([InlineKeyboardButton("👍 查看好评详情", callback_data=f"rep_voters_menu_{nominee_id}_recommend")])
    
    # 警告标签投票者按钮
    block_tags = rep_details.get('block_tags', [])
    if block_tags:
        keyboard.append([InlineKeyboardButton("👎 查看差评详情", callback_data=f"rep_voters_menu_{nominee_id}_block")])
    
    # 返回摘要按钮
    keyboard.append([InlineKeyboardButton("🔙 返回摘要", callback_data=f"rep_summary_{nominee_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

def format_reputation_details(username: str, rep_details: Dict) -> str:
    """格式化声誉详情信息"""
    recommend_tags = rep_details.get('recommend_tags', [])
    block_tags = rep_details.get('block_tags', [])
    
    text_parts = [f"🔍 **用户 @{username}** 的详细神谕", ""]
    
    if not recommend_tags and not block_tags:
        text_parts.append("📜 此人尚无神谕记录")
        return "\n".join(text_parts)
    
    # 添加推荐标签
    if recommend_tags:
        text_parts.append("👍 **好评标签**:")
        for tag in recommend_tags:
            content = tag['content']
            count = tag['count']
            text_parts.append(f"• {content} ({count})")
    
    # 添加警告标签
    if block_tags:
        if recommend_tags:
            text_parts.append("")  # 添加空行分隔
        text_parts.append("👎 **差评标签**:")
        for tag in block_tags:
            content = tag['content']
            count = tag['count']
            text_parts.append(f"• {content} ({count})")
    
    return "\n".join(text_parts)

async def show_voters_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示投票者菜单"""
    query = update.callback_query
    data = query.data
    parts = data.split('_')
    nominee_id = int(parts[-2])
    tag_type = parts[-1]
    
    caller_id = update.effective_user.id
    await update_user_activity(caller_id)
    
    # 获取被提名用户名
    username = await get_user_name(nominee_id)
    
    # 获取声誉详情
    rep_details = await get_reputation_details(nominee_id)
    
    # 选择相应类型的标签
    if tag_type == 'recommend':
        tags = rep_details.get('recommend_tags', [])
        title = f"👍 **@{username} 的好评标签投票者**"
    else:
        tags = rep_details.get('block_tags', [])
        title = f"👎 **@{username} 的差评标签投票者**"
    
    # 构建回复消息
    text_parts = [title, ""]
    if not tags:
        text_parts.append("没有相关标签")
    else:
        text_parts.append("请选择要查看的标签:")
    
    # 创建按钮 - 每个标签一个按钮
    keyboard = []
    for tag in tags[:8]:  # 限制最多8个按钮以避免超过Telegram限制
        content = tag['content']
        count = tag['count']
        tag_id = tag['id']
        keyboard.append([InlineKeyboardButton(
            f"{content} ({count})", 
            callback_data=f"rep_voters_{nominee_id}_{tag_id}"
        )])
    
    # 返回详情按钮
    keyboard.append([InlineKeyboardButton("🔙 返回详情", callback_data=f"rep_detail_{nominee_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("\n".join(text_parts), reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def show_reputation_voters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示特定标签的投票者"""
    query = update.callback_query
    data = query.data
    parts = data.split('_')
    nominee_id = int(parts[-2])
    tag_id = int(parts[-1])
    
    caller_id = update.effective_user.id
    await update_user_activity(caller_id)
    
    # 获取被提名用户名和标签信息
    username = await get_user_name(nominee_id)
    tag = await get_tag_by_id(tag_id)
    
    if not tag:
        await query.edit_message_text("标签不存在或已被删除")
        return
    
    # 获取投票者列表
    voters = await get_reputation_voters(nominee_id, tag_id)
    
    # 构建回复消息
    tag_type_emoji = "👍" if tag['tag_type'] == 'recommend' else "👎"
    text_parts = [f"{tag_type_emoji} **标签 \"{tag['content']}\" 的投票者**", ""]
    
    if not voters:
        text_parts.append("没有投票记录")
    else:
        for i, voter in enumerate(voters, start=1):
            voter_name = voter['username'] or f"用户{voter['id']}"
            vote_time = voter['created_at'].strftime("%Y-%m-%d %H:%M")
            text_parts.append(f"{i}. @{voter_name} - {vote_time}")
    
    # 创建返回按钮
    keyboard = [[InlineKeyboardButton(
        "🔙 返回标签列表", 
        callback_data=f"rep_voters_menu_{nominee_id}_{'recommend' if tag['tag_type'] == 'recommend' else 'block'}"
    )]]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("\n".join(text_parts), reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理按钮回调"""
    query = update.callback_query
    data = query.data
    
    caller_id = update.effective_user.id
    caller_username = update.effective_user.username
    await update_user_activity(caller_id, caller_username)
    
    # 处理投票相关回调
    if data.startswith("vote_"):
        parts = data.split('_')
        vote_type = parts[1]  # good 或 bad
        nominee_id = int(parts[2])
        
        # 如果是查询自己
        if nominee_id == caller_id:
            await query.answer("不能给自己投票", show_alert=True)
            return
        
        # 获取相应类型的标签
        tag_type = 'recommend' if vote_type == 'good' else 'block'
        tags = await get_tags_by_type(tag_type)
        
        if not tags:
            await query.answer(f"没有可用的{'推荐' if tag_type == 'recommend' else '警告'}标签", show_alert=True)
            return
        
        # 创建标签选择按钮
        keyboard = []
        for i, tag in enumerate(tags):
            if i % 2 == 0:
                keyboard.append([])
            keyboard[-1].append(InlineKeyboardButton(
                tag['content'], 
                callback_data=f"tag_{tag_type}_{nominee_id}_{tag['id']}"
            ))
        
        # 增加多选功能
        if tag_type == 'recommend':
            keyboard.append([InlineKeyboardButton("✅ 多选好评", callback_data=f"tag_multi_recommend_{nominee_id}")])
        else:
            keyboard.append([InlineKeyboardButton("✅ 多选差评", callback_data=f"tag_multi_block_{nominee_id}")])
        
        # 返回按钮
        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data=f"rep_summary_{nominee_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"请选择{'👍 好评' if tag_type == 'recommend' else '👎 差评'}标签:", 
            reply_markup=reply_markup
        )
    
    # 处理标签选择回调
    elif data.startswith("tag_"):
        parts = data.split('_')
        
        # 多选标签模式
        if parts[1] == "multi":
            tag_type = parts[2]  # recommend 或 block
            nominee_id = int(parts[3])
            
            # 存储多选模式的状态
            context.user_data["multi_select"] = {
                "tag_type": tag_type,
                "nominee_id": nominee_id,
                "selected_tags": []
            }
            
            # 获取该类型的所有标签
            tags = await get_tags_by_type(tag_type)
            
            # 创建标签选择按钮，带有选中状态
            keyboard = []
            for i, tag in enumerate(tags):
                if i % 2 == 0:
                    keyboard.append([])
                
                # 标记为未选中
                keyboard[-1].append(InlineKeyboardButton(
                    f"◻️ {tag['content']}", 
                    callback_data=f"tag_select_{tag_type}_{nominee_id}_{tag['id']}"
                ))
            
            # 确认和取消按钮
            keyboard.append([
                InlineKeyboardButton("✅ 确认", callback_data=f"tag_confirm_{tag_type}_{nominee_id}"),
                InlineKeyboardButton("❌ 取消", callback_data=f"rep_summary_{nominee_id}")
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"请选择多个{'👍 好评' if tag_type == 'recommend' else '👎 差评'}标签，然后点击确认:", 
                reply_markup=reply_markup
            )
            return
        
        # 处理多选模式下的标签选择
        elif parts[1] == "select":
