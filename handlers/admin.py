from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from database import db_cursor
import logging

logger = logging.getLogger(__name__)

# --- 权限检查装饰器 ---
def admin_required(func):
    """一个装饰器，用于检查用户是否是管理员。"""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        with db_cursor() as cur:
            cur.execute("SELECT is_admin FROM users WHERE id = %s", (user_id,))
            user_data = cur.fetchone()
        
        if user_data and user_data['is_admin']:
            return await func(update, context, *args, **kwargs)
        else:
            # 对非管理员，静默处理或只在私聊中提示
            if update.message.chat.type == 'private':
                await update.message.reply_text("❌ 抱歉，此命令仅限管理员使用。")
            return
    return wrapped

# --- 管理员命令 ---

@admin_required
async def set_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """将一个用户设置为管理员。"""
    if not context.args:
        await update.message.reply_text("请提供用户ID。用法: /setadmin <user_id>")
        return
    try:
        user_to_admin_id = int(context.args[0])
        with db_cursor() as cur:
            cur.execute("UPDATE users SET is_admin = TRUE WHERE id = %s", (user_to_admin_id,))
            if cur.rowcount > 0:
                await update.message.reply_text(f"✅ 用户 {user_to_admin_id} 已被设为管理员。")
            else:
                await update.message.reply_text(f"🤔 未找到用户 {user_to_admin_id}。请确保该用户已与机器人互动过。")
    except (ValueError, IndexError):
        await update.message.reply_text("无效的用户ID。请输入一个纯数字ID。")

@admin_required
async def list_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """列出所有标签。"""
    with db_cursor() as cur:
        cur.execute("SELECT tag_text, tag_type FROM tags ORDER BY tag_type, id")
        tags = cur.fetchall()
        if not tags:
            await update.message.reply_text("标签库是空的。")
            return
        
        text = "🏷️ *当前标签库:*\n\n"
        text += "*推荐类 (👍):*\n"
        text += "\n".join([f"\- `{tag['tag_text']}`" for tag in tags if tag['tag_type'] == 1])
        text += "\n\n*拉黑类 (👎):*\n"
        text += "\n".join([f"\- `{tag['tag_text']}`" for tag in tags if tag['tag_type'] == -1])
        
        await update.message.reply_text(text, parse_mode='MarkdownV2')

@admin_required
async def add_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """添加一个新标签。"""
    try:
        tag_type_str = context.args[0]
        tag_text = " ".join(context.args[1:])
        
        if not tag_text:
            raise IndexError

        if tag_type_str == "推荐":
            tag_type = 1
        elif tag_type_str == "拉黑":
            tag_type = -1
        else:
            await update.message.reply_text("标签类型错误。请使用 '推荐' 或 '拉黑'。")
            return

        with db_cursor() as cur:
            cur.execute("INSERT INTO tags (tag_text, tag_type) VALUES (%s, %s)", (tag_text, tag_type))
        await update.message.reply_text(f"✅ 标签 '{tag_text}' 已添加到 '{tag_type_str}' 类别。")

    except IndexError:
        await update.message.reply_text("格式错误。用法: /addtag <推荐|拉黑> <标签内容>")

@admin_required
async def remove_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """移除一个标签。(修正了装饰器名称)"""
    try:
        tag_text = " ".join(context.args)
        if not tag_text:
            raise IndexError

        with db_cursor() as cur:
            cur.execute("DELETE FROM tags WHERE tag_text = %s", (tag_text,))
            if cur.rowcount > 0:
                await update.message.reply_text(f"✅ 标签 '{tag_text}' 已被移除。")
            else:
                await update.message.reply_text(f"🤔 未找到名为 '{tag_text}' 的标签。")
    except IndexError:
        await update.message.reply_text("格式错误。用法: /removetag <标签内容>")
