import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from database import get_setting

# 日志记录
logger = logging.getLogger(__name__)

async def delete_message_callback(context: ContextTypes.DEFAULT_TYPE):
    """定时任务的回调函数，用于删除消息。"""
    job = context.job
    chat_id = job.chat_id
    message_id = job.data
    
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"自动删除了消息 {message_id} (Chat ID: {chat_id})")
    except BadRequest as e:
        if "message to delete not found" in e.message.lower():
            logger.warning(f"尝试删除消息 {message_id} 时失败：消息已被删除或不存在。")
        else:
            logger.error(f"删除消息 {message_id} 时发生错误: {e}")
    except Exception as e:
        logger.error(f"删除消息 {message_id} 时发生未知错误: {e}")

async def schedule_message_deletion(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    """
    为指定消息安排一个定时删除任务。
    如果已存在同名任务，会先移除旧的，再创建新的，以实现“重置计时器”的效果。
    """
    # 从数据库获取自动删除的秒数，默认300秒（5分钟）
    timeout_str = await get_setting('auto_delete_timeout', '300')
    try:
        timeout_seconds = int(timeout_str)
    except (ValueError, TypeError):
        timeout_seconds = 300
        logger.warning(f"数据库中的 auto_delete_timeout ('{timeout_str}') 不是有效数字，已使用默认值 300 秒。")

    if timeout_seconds <= 0:
        # 如果设置为0或负数，则不执行删除
        return

    job_name = f"delete_{chat_id}_{message_id}"

    # 移除可能已存在的同名任务
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    for job in current_jobs:
        job.schedule_removal()
        logger.debug(f"移除了旧的删除任务: {job_name}")

    # 创建新的定时删除任务
    context.job_queue.run_once(
        delete_message_callback,
        when=timeout_seconds,
        chat_id=chat_id,
        data=message_id,
        name=job_name
    )
    logger.debug(f"为消息 {message_id} 安排了 {timeout_seconds} 秒后的删除任务: {job_name}")
