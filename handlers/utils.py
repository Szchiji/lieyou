import logging
from telegram.ext import ContextTypes
from database import get_setting

logger = logging.getLogger(__name__)

async def schedule_message_deletion(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    """
    根据数据库中的设置，调度一个任务来删除消息。
    """
    try:
        timeout_str = await get_setting('auto_delete_timeout', '300')
        timeout = int(timeout_str)
        
        if timeout > 0:
            context.job_queue.run_once(delete_message, timeout, data={'chat_id': chat_id, 'message_id': message_id}, name=f"delete_{chat_id}_{message_id}")
            logger.debug(f"已为消息 {chat_id}-{message_id} 安排 {timeout} 秒后删除。")

    except (ValueError, TypeError) as e:
        logger.error(f"无法解析 auto_delete_timeout 设置: {e}。将使用默认值300秒。")
        context.job_queue.run_once(delete_message, 300, data={'chat_id': chat_id, 'message_id': message_id}, name=f"delete_{chat_id}_{message_id}")

async def delete_message(context: ContextTypes.DEFAULT_TYPE):
    """
    由 JobQueue 调用的回调函数，用于实际删除消息。
    """
    job = context.job
    chat_id = job.data['chat_id']
    message_id = job.data['message_id']
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.debug(f"已成功删除消息 {chat_id}-{message_id}。")
    except Exception as e:
        # 忽略 "Message to delete not found" 错误，这通常意味着消息已被手动删除
        if "Message to delete not found" in str(e):
            logger.debug(f"尝试删除的消息 {chat_id}-{message_id} 已不存在。")
        else:
            logger.error(f"删除消息 {chat_id}-{message_id} 时发生错误: {e}")
