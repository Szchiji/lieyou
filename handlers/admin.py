import logging
from telegram import Update
from telegram.ext import ContextTypes
from database import db_cursor

logger = logging.getLogger(__name__)

async def check_admin(user_id: int) -> bool:
    async with db_cursor() as cur:
        user = await cur.fetchrow("SELECT is_admin FROM users WHERE id = $1", user_id)
        return user and user['is_admin']

async def set_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update.effective_user.id):
        await update.message.reply_text("你没有此权限。")
        return
    try:
        target_user_id = int(context.args[0])
        async with db_cursor() as cur:
            await cur.execute("UPDATE users SET is_admin = TRUE WHERE id = $1", target_user_id)
        await update.message.reply_text(f"用户 {target_user_id} 已被设置为管理员。")
    except (IndexError, ValueError):
        await update.message.reply_text("用法: /setadmin <user_id>")

async def list_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update.effective_user.id): return
    async with db_cursor() as cur:
        tags = await cur.fetch("SELECT tag_name, type FROM tags ORDER BY type, tag_name")
    if not tags:
        await update.message.reply_text("还没有任何标签。")
        return
    
    rec_tags = "\n".join([f"- {t['tag_name']}" for t in tags if t['type'] == 'recommend'])
    block_tags = "\n".join([f"- {t['tag_name']}" for t in tags if t['type'] == 'block'])
    await update.message.reply_text(f"推荐标签:\n{rec_tags}\n\n拉黑标签:\n{block_tags}")

async def add_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update.effective_user.id): return
    try:
        tag_type_str, tag_name = context.args[0], " ".join(context.args[1:])
        tag_type = 'recommend' if tag_type_str == '推荐' else 'block'
        async with db_cursor() as cur:
            await cur.execute("INSERT INTO tags (tag_name, type) VALUES ($1, $2)", tag_name, tag_type)
        await update.message.reply_text(f"标签 '{tag_name}' 已添加。")
    except Exception:
        await update.message.reply_text("用法: /addtag <推荐|拉黑> <标签名>")

async def remove_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update.effective_user.id): return
    try:
        tag_name = " ".join(context.args)
        async with db_cursor() as cur:
            await cur.execute("DELETE FROM tags WHERE tag_name = $1", tag_name)
        await update.message.reply_text(f"标签 '{tag_name}' 已移除。")
    except Exception:
        await update.message.reply_text("用法: /removetag <标签名>")
