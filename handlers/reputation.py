import logging
import re
from typing import List, Dict, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import (
    db_fetch_all, db_fetch_one, db_fetchval, db_execute, db_transaction,
    update_user_activity, get_or_create_user_by_username
    # 移除了 get_random_motto
)

logger = logging.getLogger(__name__)

async def handle_nomination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理群聊中的@用户提名"""
    message_text = update.message.text
    user_id = update.effective_user.id
    
    await update_user_activity(user_id, update.effective_user.username, update.effective_user.first_name)
    
    # 提取用户名
    username_match = re.search(r'@(\w{5,})', message_text)
    if not username_match:
        return
    
    username = username_match.group(1)
    
    # 使用新函数获取或创建用户
    target_user = await get_or_create_user_by_username(username)
    if not target_user:
        await update.message.reply_text(f"❌ 处理用户 @{username} 时出错，请稍后重试。")
        return
    
    # 检查是否是自己
    if target_user['id'] == user_id:
        await update.message.reply_text("🚫 不能对自己进行评价。")
        return
    
    await show_reputation_summary(update, context, target_user['id'], from_query=True)

async def handle_username_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理私聊中的用户名查询"""
    message_text = update.message.text
    user_id = update.effective_user.id
    
    await update_user_activity(user_id, update.effective_user.username, update.effective_user.first_name)
    
    # 提取用户名
    username_match = re.search(r'查询\s+@(\w{5,})', message_text)
    if not username_match:
        return
    
    username = username_match.group(1)
    
    # 使用新函数获取或创建用户
    target_user = await get_or_create_user_by_username(username)
    if not target_user:
        await update.message.reply_text(f"❌ 处理用户 @{username} 时出错，请稍后重试。")
        return

    # 检查是否是自己
    if target_user['id'] == user_id:
        await update.message.reply_text("🚫 不能查询自己的声誉。")
        return
    
    await show_reputation_summary(update, context, target_user['id'], from_query=True)

async def show_reputation_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, target_id: int = None, from_query: bool = False):
    """显示用户声誉概览"""
    query = update.callback_query
    
    if target_id is None and query:
        data_parts = query.data.split("_")
        target_id = int(data_parts[2])
    
    if query and not from_query:
        await query.answer()
    
    target_user = await db_fetch_one("SELECT username, first_name FROM users WHERE id = $1", target_id)
    if not target_user:
        error_msg = "❌ 用户不存在"
        if from_query:
            await update.message.reply_text(error_msg)
        else:
            await query.edit_message_text(error_msg)
        return
    
    stats = await db_fetch_one("""
        SELECT 
            COUNT(*) as total_votes,
            COUNT(*) FILTER (WHERE is_positive = TRUE) as positive_votes,
            COUNT(*) FILTER (WHERE is_positive = FALSE) as negative_votes,
            COUNT(DISTINCT voter_id) as unique_voters
        FROM reputations WHERE target_id = $1
    """, target_id)
    
    total_votes = stats['total_votes'] or 0
    positive_votes = stats['positive_votes'] or 0
    negative_votes = stats['negative_votes'] or 0
    
    if total_votes > 0:
        reputation_score = round((positive_votes / total_votes) * 100)
    else:
        reputation_score = 0
    
    username = target_user.get('username')
    display_name = target_user.get('first_name') or (f"@{username}" if username else f"用户{target_id}")
    clean_username = username or display_name
    
    if len(clean_username) > 15:
        clean_username = clean_username[:12] + "..."

    if total_votes == 0:
        reputation_desc = "中立 (0)"
        reputation_icon = "⚖️"
    elif reputation_score >= 90:
        reputation_desc = f"极佳声誉 ({reputation_score}%)"
        reputation_icon = "🌟"
    elif reputation_score >= 75:
        reputation_desc = f"良好声誉 ({reputation_score}%)"
        reputation_icon = "✅"
    elif reputation_score >= 60:
        reputation_desc = f"一般声誉 ({reputation_score}%)"
        reputation_icon = "⚖️"
    elif reputation_score >= 40:
        reputation_desc = f"较差声誉 ({reputation_score}%)"
        reputation_icon = "⚠️"
    else:
        reputation_desc = f"负面声誉 ({reputation_score}%)"
        reputation_icon = "💀"
    
    # 移除了便签 (motto) 功能
    
    message = f"┏━━━━「 📜 神谕之卷 」━━━━┓\n"
    message += f"┃                          ┃\n"
    message += f"┃  👤 求问对象: @{clean_username}   ┃\n"
    message += f"┃                          ┃\n"
    message += f"┃  👍 赞誉: {positive_votes} 次        ┃\n"
    message += f"┃  👎 警示: {negative_votes} 次        ┃\n"
    message += f"┃  {reputation_icon} 神谕判定: {reputation_desc}  ┃\n"
    message += f"┃                          ┃\n"
    message += f"┗━━━━━━━━━━━━━━━━━━┛"
    
    keyboard = []
    
    if total_votes > 0:
        keyboard.append([
            InlineKeyboardButton("📝 详细评价", callback_data=f"rep_detail_{target_id}"),
            InlineKeyboardButton("👥 评价者", callback_data=f"rep_voters_menu_{target_id}_1")
        ])
    
    current_user_id = update.effective_user.id
    if target_id != current_user_id:
        action_buttons = []
        existing_vote = await db_fetch_one(
            "SELECT is_positive, tag_ids FROM reputations WHERE target_id = $1 AND voter_id = $2",
            target_id, current_user_id
        )
        
        if existing_vote:
            action_buttons.append(InlineKeyboardButton(f"✏️ 修改评价", callback_data=f"vote_edit_{target_id}"))
        else:
            action_buttons.extend([
                InlineKeyboardButton("👍 好评", callback_data=f"vote_positive_{target_id}"),
                InlineKeyboardButton("👎 差评", callback_data=f"vote_negative_{target_id}")
            ])
        
        is_favorited = await db_fetchval(
            "SELECT EXISTS(SELECT 1 FROM favorites WHERE user_id = $1 AND target_id = $2)",
            current_user_id, target_id
        )
        fav_text = "💔 取消收藏" if is_favorited else "💖 收藏"
        action_buttons.append(InlineKeyboardButton(fav_text, callback_data=f"toggle_favorite_{target_id}"))
        keyboard.append(action_buttons)
    
    keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if from_query:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

# --- 其他函数保持不变 ---
# (show_reputation_details, show_voters_menu, show_reputation_voters, 等等...)
# ... (将你提供的文件中的其他函数粘贴到这里)
async def show_reputation_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示详细评价"""
    query = update.callback_query
    await query.answer()
    
    data_parts = query.data.split("_")
    target_id = int(data_parts[2])
    
    target_user = await db_fetch_one("SELECT username, first_name FROM users WHERE id = $1", target_id)
    display_name = target_user['first_name'] or f"@{target_user['username']}" if target_user['username'] else f"用户{target_id}"
    
    details = await db_fetch_all("""
        SELECT r.is_positive, r.tag_ids, r.comment, r.created_at, u.first_name, u.username
        FROM reputations r LEFT JOIN users u ON r.voter_id = u.id
        WHERE r.target_id = $1 ORDER BY r.created_at DESC LIMIT 20
    """, target_id)
    
    if not details:
        await query.edit_message_text(f"📝 **{display_name}** 的详细评价\n\n暂无评价记录。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"rep_summary_{target_id}")]]), parse_mode=ParseMode.MARKDOWN)
        return
    
    all_tags = await db_fetch_all("SELECT id, name, type FROM tags")
    tag_dict = {tag['id']: {'name': tag['name'], 'type': tag['type']} for tag in all_tags}
    
    message = f"📝 **{display_name}** 的详细评价\n\n"
    positive_count = sum(1 for d in details if d['is_positive'])
    negative_count = len(details) - positive_count
    message += f"👍 好评: {positive_count} 条\n"
    message += f"👎 差评: {negative_count} 条\n\n"
    
    for i, detail in enumerate(details[:10], 1):
        voter_name = detail['first_name'] or detail['username'] or "匿名用户"
        vote_type = "👍" if detail['is_positive'] else "👎"
        message += f"{i}. {vote_type} {voter_name}"
        
        if detail['tag_ids']:
            tag_names = []
            for tag_id in detail['tag_ids']:
                if tag_id in tag_dict:
                    tag_info = tag_dict[tag_id]
                    emoji = "🏅" if tag_info['type'] == 'recommend' else "⚠️"
                    tag_names.append(f"{emoji}{tag_info['name']}")
            if tag_names: message += f" [{', '.join(tag_names)}]"
        
        if detail['comment']:
            comment = detail['comment'][:50] + "..." if len(detail['comment']) > 50 else detail['comment']
            message += f"\n   💬 {comment}"
        message += "\n"
    
    if len(details) > 10: message += f"\n... 还有 {len(details) - 10} 条评价"
    
    keyboard = [[InlineKeyboardButton("👥 查看评价者", callback_data=f"rep_voters_menu_{target_id}_1")], [InlineKeyboardButton("🔙 返回概览", callback_data=f"rep_summary_{target_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def show_voters_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data_parts = query.data.split("_")
    target_id = int(data_parts[3])
    page = int(data_parts[4])
    
    target_user = await db_fetch_one("SELECT username, first_name FROM users WHERE id = $1", target_id)
    display_name = target_user['first_name'] or f"@{target_user['username']}" if target_user['username'] else f"用户{target_id}"
    message = f"👥 **{display_name}** 的评价者\n\n选择查看类型："
    
    stats = await db_fetch_one("SELECT COUNT(*) FILTER (WHERE is_positive = TRUE) as positive_count, COUNT(*) FILTER (WHERE is_positive = FALSE) as negative_count FROM reputations WHERE target_id = $1", target_id)
    positive_count = stats['positive_count'] or 0
    negative_count = stats['negative_count'] or 0
    
    keyboard = []
    if positive_count > 0: keyboard.append([InlineKeyboardButton(f"👍 好评者 ({positive_count})", callback_data=f"rep_voters_positive_{target_id}_{page}")])
    if negative_count > 0: keyboard.append([InlineKeyboardButton(f"👎 差评者 ({negative_count})", callback_data=f"rep_voters_negative_{target_id}_{page}")])
    keyboard.append([InlineKeyboardButton("👥 全部评价者", callback_data=f"rep_voters_all_{target_id}_{page}"), InlineKeyboardButton("🔙 返回", callback_data=f"rep_summary_{target_id}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def show_reputation_voters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data_parts = query.data.split("_")
    vote_type = data_parts[2]
    target_id = int(data_parts[3])
    page = int(data_parts[4])
    
    target_user = await db_fetch_one("SELECT username, first_name FROM users WHERE id = $1", target_id)
    display_name = target_user['first_name'] or f"@{target_user['username']}" if target_user['username'] else f"用户{target_id}"
    
    per_page = 8
    offset = (page - 1) * per_page
    if vote_type == "positive": where_clause, title = "AND r.is_positive = TRUE", "👍 好评者"
    elif vote_type == "negative": where_clause, title = "AND r.is_positive = FALSE", "👎 差评者"
    else: where_clause, title = "", "👥 全部评价者"
    
    voters = await db_fetch_all(f"SELECT u.id, u.username, u.first_name, r.is_positive, r.created_at FROM reputations r JOIN users u ON r.voter_id = u.id WHERE r.target_id = $1 {where_clause} ORDER BY r.created_at DESC LIMIT $2 OFFSET $3", target_id, per_page, offset)
    total_count = await db_fetchval(f"SELECT COUNT(*) FROM reputations r WHERE r.target_id = $1 {where_clause}", target_id)
    total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 1
    
    message = f"{title} - **{display_name}**\n\n"
    if not voters: message += "暂无评价者。"
    else:
        for i, voter in enumerate(voters, (page - 1) * per_page + 1):
            voter_name = voter['first_name'] or voter['username'] or f"用户{voter['id']}"
            vote_icon = "👍" if voter['is_positive'] else "👎"
            message += f"{i}. {vote_icon} {voter_name}\n"
        if total_pages > 1: message += f"\n第 {page}/{total_pages} 页"
    
    keyboard = []
    if total_pages > 1:
        nav_buttons = []
        if page > 1: nav_buttons.append(InlineKeyboardButton("◀️ 上一页", callback_data=f"rep_voters_{vote_type}_{target_id}_{page-1}"))
        if page < total_pages: nav_buttons.append(InlineKeyboardButton("▶️ 下一页", callback_data=f"rep_voters_{vote_type}_{target_id}_{page+1}"))
        if nav_buttons: keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("🔄 切换类型", callback_data=f"rep_voters_menu_{target_id}_{page}"), InlineKeyboardButton("🔙 返回概览", callback_data=f"rep_summary_{target_id}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    await update_user_activity(user_id, update.effective_user.username, update.effective_user.first_name)
    if data.startswith("vote_"): await handle_vote_button(update, context)
    elif data.startswith("tag_"): await handle_tag_selection(update, context)
    elif data.startswith("toggle_favorite_"): await handle_favorite_toggle(update, context)

async def handle_vote_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    data_parts = data.split("_")
    action = data_parts[1]
    target_id = int(data_parts[2])
    
    if target_id == user_id: await query.answer("❌ 不能对自己进行评价", show_alert=True); return
    target_user = await db_fetch_one("SELECT username, first_name FROM users WHERE id = $1", target_id)
    if not target_user: await query.answer("❌ 用户不存在", show_alert=True); return
    
    display_name = target_user['first_name'] or f"@{target_user['username']}" if target_user['username'] else f"用户{target_id}"
    
    if action in ["positive", "edit"]:
        tags = await db_fetch_all("SELECT id, name FROM tags WHERE type = 'recommend' ORDER BY name")
        vote_type_text, is_positive = "好评", True
    else:
        tags = await db_fetch_all("SELECT id, name FROM tags WHERE type = 'block' ORDER BY name")
        vote_type_text, is_positive = "差评", False
    
    existing_vote = None
    if action == "edit":
        existing_vote = await db_fetch_one("SELECT is_positive, tag_ids, comment FROM reputations WHERE target_id = $1 AND voter_id = $2", target_id, user_id)
        if existing_vote:
            is_positive = existing_vote['is_positive']
            vote_type_text = "好评" if is_positive else "差评"
            tag_type = 'recommend' if is_positive else 'block'
            tags = await db_fetch_all("SELECT id, name FROM tags WHERE type = $1 ORDER BY name", tag_type)
    
    message = f"📝 给 **{display_name}** 评价 - {vote_type_text}\n\n选择适合的标签 (可多选)，然后提交评价："
    keyboard = []
    selected_tags = existing_vote['tag_ids'] if existing_vote else []
    
    for i in range(0, len(tags), 2):
        row = []
        for j in range(2):
            if i + j < len(tags):
                tag = tags[i + j]
                is_selected = tag['id'] in selected_tags
                prefix = "✅ " if is_selected else ""
                row.append(InlineKeyboardButton(f"{prefix}{tag['name']}", callback_data=f"tag_toggle_{target_id}_{is_positive}_{tag['id']}"))
        keyboard.append(row)
    
    keyboard.extend([[InlineKeyboardButton("💬 添加评论", callback_data=f"vote_comment_{target_id}_{is_positive}")], [InlineKeyboardButton("✅ 提交评价", callback_data=f"vote_submit_{target_id}_{is_positive}")], [InlineKeyboardButton("❌ 取消", callback_data=f"rep_summary_{target_id}")],])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    context.user_data['current_vote'] = {'target_id': target_id, 'is_positive': is_positive, 'selected_tags': selected_tags, 'comment': existing_vote['comment'] if existing_vote else None}
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def handle_tag_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    data_parts = data.split("_")
    target_id = int(data_parts[2])
    tag_id = int(data_parts[4])
    
    current_vote = context.user_data.get('current_vote', {})
    if current_vote.get('target_id') != target_id: await query.answer("❌ 状态错误，请重新开始", show_alert=True); return
    
    selected_tags = current_vote.get('selected_tags', [])
    if tag_id in selected_tags: selected_tags.remove(tag_id)
    else: selected_tags.append(tag_id)
    
    current_vote['selected_tags'] = selected_tags
    context.user_data['current_vote'] = current_vote
    await handle_vote_button(update, context)

async def handle_vote_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    data_parts = data.split("_")
    target_id = int(data_parts[2])
    is_positive = data_parts[3] == "True"
    await query.answer()
    
    target_user = await db_fetch_one("SELECT username, first_name FROM users WHERE id = $1", target_id)
    display_name = target_user['first_name'] or f"@{target_user['username']}" if target_user['username'] else f"用户{target_id}"
    vote_type_text = "好评" if is_positive else "差评"
    
    message = f"💬 **为 {display_name} 添加评论** - {vote_type_text}\n\n请发送您的评论内容（最多200字符）：\n\n发送 /cancel 取消操作"
    keyboard = [[InlineKeyboardButton("🔙 返回", callback_data=f"vote_{'positive' if is_positive else 'negative'}_{target_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    context.user_data['comment_input'] = {'target_id': target_id, 'is_positive': is_positive}

async def handle_vote_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    data_parts = data.split("_")
    target_id = int(data_parts[2])
    is_positive = data_parts[3] == "True"
    await query.answer()
    
    current_vote = context.user_data.get('current_vote', {})
    if current_vote.get('target_id') != target_id: await query.answer("❌ 状态错误，请重新开始", show_alert=True); return
    
    selected_tags = current_vote.get('selected_tags', [])
    comment = current_vote.get('comment')
    
    try:
        async with db_transaction() as conn:
            await conn.execute("""
                INSERT INTO reputations (target_id, voter_id, is_positive, tag_ids, comment) VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (target_id, voter_id) DO UPDATE SET is_positive = $3, tag_ids = $4, comment = $5, created_at = NOW()
            """, target_id, user_id, is_positive, selected_tags, comment)
        
        if 'current_vote' in context.user_data: del context.user_data['current_vote']
        
        target_user = await db_fetch_one("SELECT username, first_name FROM users WHERE id = $1", target_id)
        display_name = target_user['first_name'] or f"@{target_user['username']}" if target_user['username'] else f"用户{target_id}"
        vote_type_text = "好评" if is_positive else "差评"
        
        message = f"✅ **评价提交成功**\n\n已为 **{display_name}** 提交{vote_type_text}\n"
        if selected_tags:
            tags = await db_fetch_all("SELECT id, name, type FROM tags WHERE id = ANY($1)", selected_tags)
            tag_names = []
            for tag in tags:
                emoji = "🏅" if tag['type'] == 'recommend' else "⚠️"
                tag_names.append(f"{emoji}{tag['name']}")
            if tag_names: message += f"标签: {', '.join(tag_names)}\n"
        if comment: message += f"评论: {comment}\n"
        message += "\n感谢您的评价！"
        
        keyboard = [[InlineKeyboardButton("🔍 查看用户信息", callback_data=f"rep_summary_{target_id}")], [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        
        try:
            from handlers.leaderboard import clear_leaderboard_cache
            clear_leaderboard_cache()
        except ImportError: pass
        logger.info(f"用户 {user_id} 为用户 {target_id} 提交了评价")
    except Exception as e:
        logger.error(f"提交评价失败: {e}", exc_info=True)
        await query.answer("❌ 提交评价失败，请重试", show_alert=True)

async def handle_favorite_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    target_id = int(data.split("_")[2])
    
    is_favorited = await db_fetchval("SELECT EXISTS(SELECT 1 FROM favorites WHERE user_id = $1 AND target_id = $2)", user_id, target_id)
    try:
        if is_favorited:
            await db_execute("DELETE FROM favorites WHERE user_id = $1 AND target_id = $2", user_id, target_id)
            await query.answer("💔 已取消收藏", show_alert=True)
        else:
            await db_execute("INSERT INTO favorites (user_id, target_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", user_id, target_id)
            await query.answer("💖 已添加到收藏", show_alert=True)
        await show_reputation_summary(update, context, target_id)
    except Exception as e:
        logger.error(f"切换收藏状态失败: {e}")
        await query.answer("❌ 操作失败", show_alert=True)

async def handle_comment_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    comment_input = context.user_data.get('comment_input')
    if not comment_input: return False
    
    comment = update.message.text.strip()
    if len(comment) > 200:
        await update.message.reply_text("❌ 评论内容过长，请控制在200字符以内。")
        return True
    
    target_id = comment_input['target_id']
    is_positive = comment_input['is_positive']
    
    current_vote = context.user_data.get('current_vote', {})
    current_vote['comment'] = comment
    context.user_data['current_vote'] = current_vote
    del context.user_data['comment_input']
    
    target_user = await db_fetch_one("SELECT username, first_name FROM users WHERE id = $1", target_id)
    display_name = target_user['first_name'] or f"@{target_user['username']}" if target_user['username'] else f"用户{target_id}"
    vote_type_text = "好评" if is_positive else "差评"
    
    message = f"✅ **评论已添加**\n\n为 **{display_name}** 的{vote_type_text}添加了评论：\n💬 {comment}\n\n现在可以提交评价了。"
    keyboard = [[InlineKeyboardButton("✅ 提交评价", callback_data=f"vote_submit_{target_id}_{is_positive}")], [InlineKeyboardButton("🔙 返回编辑", callback_data=f"vote_{'positive' if is_positive else 'negative'}_{target_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    return True
