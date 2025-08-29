from telegram import Update
from telegram.ext import ContextTypes
from database import db_cursor
import logging

logger = logging.getLogger(__name__)

async def check_admin(user_id: int) -> bool:
    """检查用户是否为管理员。"""
    with db_cursor() as cur:
        cur.execute("SELECT is_admin FROM users WHERE id = %s", (user_id,))
        result = cur.fetchone()
        return result and result['is_admin']

async def set_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """将用户设置为管理员（仅能由已有管理员操作）。"""
    user = update.effective_user
    if not await check_admin(user.id):
        await update.message.reply_text("你没有权限执行此操作。")
        return
    
    if not context.args:
        await update.message.reply_text("用法: /setadmin <user_id>")
        return
        
    try:
        target_id = int(context.args[0])
        with db_cursor() as cur:
            cur.execute("UPDATE users SET is_admin = TRUE WHERE id = %s", (target_id,))
        await update.message.reply_text(f"用户 {target_id} 已被设为管理员。")
    except (ValueError, IndexError):
        await update.message.reply_text("请输入有效的用户ID。")

async def list_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """列出所有系统预设标签。"""
    if not await check_admin(update.effective_user.id):
        await update.message.reply_text("你没有权限执行此操作。")
        return

    with db_cursor() as cur:
        cur.execute("SELECT tag_text, tag_type FROM tags ORDER BY tag_type, tag_text")
        tags = cur.fetchall()
        
        upvote_tags = [t['tag_text'] for t in tags if t['tag_type'] == 1]
        downvote_tags = [t['tag_text'] for t in tags if t['tag_type'] == -1]
        
        text = "👍 **推荐标签**:\n" + ", ".join(upvote_tags) + "\n\n"
        text += "👎 **拉黑标签**:\n" + ", ".join(downvote_tags)
        
        await update.message.reply_text(text)

async def add_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """添加一个新的预设标签。"""
    if not await check_admin(update.effective_user.id):
        await update.message.reply_text("你没有权限执行此操作。")
        return

    try:
        tag_type_str = context.args[0].lower()
        tag_text = " ".join(context.args[1:])
        
        if tag_type_str not in ['推荐', 'up', '拉黑', 'down']:
            raise ValueError("类型错误")
        if not tag_text:
            raise ValueError("文本为空")
            
        tag_type = 1 if tag_type_str in ['推荐', 'up'] else -1
        
        with db_cursor() as cur:
            cur.execute(
                "INSERT INTO tags (tag_text, tag_type) VALUES (%s, %s)",
                (tag_text, tag_type)
            )
        await update.message.reply_text(f"标签 '{tag_text}' 已成功添加。")
        
    except (IndexError, ValueError):
        await update.message.reply_text("用法: /addtag <推荐|拉黑> <标签文本>")

async def remove_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """移除一个预设标签。"""
    if not await check_admin(update.effective_user.id):
        await update.message.reply_text("你没有权限执行此操作。")
        return

    try:
        tag_text = " ".join(context.args)
        if not tag_text:
            raise ValueError
        
        with db_cursor() as cur:
            cur.execute("DELETE FROM tags WHERE tag_text = %s", (tag_text,))
            if cur.rowcount == 0:
                await update.message.reply_text(f"未找到标签 '{tag_text}'。")
            else:
                await update.message.reply_text(f"标签 '{tag_text}' 已被移除。")

    except (IndexError, ValueError):
        await update.message.reply_text("用法: /removetag <标签文本>")
