import logging
from telegram import Update
from telegram.ext import ContextTypes
from database import db_cursor

logger = logging.getLogger(__name__)

async def is_admin(user_id: int) -> bool:
    async with db_cursor() as cur:
        user = await cur.fetchrow("SELECT is_admin FROM users WHERE id = $1", user_id)
        return user and user['is_admin']

async def set_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("你没有权限执行此操作。")
        return
    try:
        target_id = int(context.args[0])
        async with db_cursor() as cur:
            await cur.execute("UPDATE users SET is_admin = TRUE WHERE id = $1", target_id)
        await update.message.reply_text(f"用户 {target_id} 已被设置为管理员。")
    except (IndexError, ValueError):
        await update.message.reply_text("用法: /setadmin <user_id>")

async def list_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    async with db_cursor() as cur:
        tags = await cur.fetch("SELECT tag_name, type FROM tags ORDER BY type, tag_name")
    if not tags:
        await update.message.reply_text("系统中还没有标签。")
        return
    
    rec_tags = [t['tag_name'] for t in tags if t['type'] == 'recommend']
    block_tags = [t['tag_name'] for t in tags if t['type'] == 'block']
    
    text = "👍 推荐标签:\n" + (', '.join(rec_tags) or '无')
    text += "\n\n👎 拉黑标签:\n" + (', '.join(block_tags) or '无')
    await update.message.reply_text(text)

async def add_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    try:
        tag_type_chinese, tag_name = context.args[0], context.args[1]
        if tag_type_chinese not in ['推荐', '拉黑']:
            await update.message.reply_text("标签类型必须是 '推荐' 或 '拉黑'。")
            return
            
        tag_type = 'recommend' if tag_type_chinese == '推荐' else 'block'
        
        # --- 核心修正：使用100%正确的字段名 `tag_name` ---
        async with db_cursor() as cur:
            await cur.execute("INSERT INTO tags (tag_name, type) VALUES ($1, $2) ON CONFLICT (tag_name) DO NOTHING", tag_name, tag_type)
        await update.message.reply_text(f"标签 '{tag_name}' ({tag_type_chinese}) 已添加。")
    except (IndexError, ValueError):
        await update.message.reply_text("用法: /addtag <推荐|拉黑> <标签名>")
    except Exception as e:
        logger.error(f"添加标签时出错: {e}", exc_info=True)
        await update.message.reply_text("添加标签时发生错误。")


async def remove_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    try:
        tag_name = context.args[0]
        async with db_cursor() as cur:
            # 删除标签时，相关的投票记录也会因为 CASCADE 约束被自动删除
            await cur.execute("DELETE FROM tags WHERE tag_name = $1", tag_name)
        await update.message.reply_text(f"标签 '{tag_name}' 已移除。")
    except (IndexError, ValueError):
        await update.message.reply_text("用法: /removetag <标签名>")
