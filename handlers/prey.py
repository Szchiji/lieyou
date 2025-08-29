from telegram import Update
from telegram.ext import ContextTypes
from database import get_db_cursor
import logging

logger = logging.getLogger(__name__)

async def trap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """捕捉一只新的猎物。"""
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("请提供猎物名称。用法: /trap <猎物名称>")
        return

    prey_name = " ".join(context.args)
    logger.info(f"用户 {user_id} 正在尝试捕捉猎物: {prey_name}")
    try:
        with get_db_cursor() as cur:
            cur.execute(
                "INSERT INTO prey (owner_id, name) VALUES (%s, %s) RETURNING id",
                (user_id, prey_name)
            )
            prey_id = cur.fetchone()[0]
        await update.message.reply_text(f"成功捕获猎物: {prey_name}！\n它的ID是: {prey_id}")
        logger.info(f"用户 {user_id} 成功捕获猎物 {prey_name} (ID: {prey_id})")
    except Exception as e:
        logger.error(f"捕捉猎物时出错，用户ID: {user_id}。错误: {e}")
        await update.message.reply_text("捕捉失败，数据库发生错误。")

async def list_prey(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """列出用户所有未被狩猎的猎物。"""
    user_id = update.effective_user.id
    logger.info(f"用户 {user_id} 请求猎物列表。")
    try:
        with get_db_cursor() as cur:
            cur.execute(
                "SELECT id, name, trapped_at FROM prey WHERE owner_id = %s AND is_hunted = FALSE ORDER BY trapped_at ASC",
                (user_id,)
            )
            preys = cur.fetchall()

        if not preys:
            await update.message.reply_text("你的陷阱空空如也，快去 /trap 一些猎物吧！")
            return

        message = "你捕获的猎物:\n\n"
        for prey in preys:
            message += f"ID: {prey[0]} - {prey[1]} (捕获于: {prey[2].strftime('%Y-%m-%d %H:%M')})\n"
        
        await update.message.reply_text(message)
    except Exception as e:
        logger.error(f"列出猎物时出错，用户ID: {user_id}。错误: {e}")
        await update.message.reply_text("获取列表失败，数据库发生错误。")

async def hunt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """狩猎一只猎物，并为用户增加声望。"""
    user_id = update.effective_user.id
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("请提供有效的猎物ID。用法: /hunt <猎物ID>")
        return

    prey_id = int(context.args[0])
    logger.info(f"用户 {user_id} 正在尝试狩猎猎物ID: {prey_id}")
    try:
        with get_db_cursor() as cur:
            # 检查猎物是否存在且属于该用户
            cur.execute(
                "SELECT name FROM prey WHERE id = %s AND owner_id = %s AND is_hunted = FALSE",
                (prey_id, user_id)
            )
            prey = cur.fetchone()

            if not prey:
                await update.message.reply_text("找不到这个猎物，它可能已经被狩猎或不属于你。")
                return
            
            prey_name = prey[0]

            # 标记猎物为已狩猎
            cur.execute(
                "UPDATE prey SET is_hunted = TRUE, hunted_at = CURRENT_TIMESTAMP WHERE id = %s",
                (prey_id,)
            )

            # 增加用户声望
            cur.execute(
                "UPDATE users SET reputation = reputation + 1 WHERE id = %s RETURNING reputation",
                (user_id,)
            )
            new_reputation = cur.fetchone()[0]

        await update.message.reply_text(f"恭喜！你成功狩猎了 {prey_name}！\n你的声望提升了，现在是: {new_reputation}。")
        logger.info(f"用户 {user_id} 成功狩猎猎物 {prey_name} (ID: {prey_id})，新声望: {new_reputation}")
    except Exception as e:
        logger.error(f"狩猎猎物时出错，用户ID: {user_id}。错误: {e}")
        await update.message.reply_text("狩猎失败，数据库发生错误。")
