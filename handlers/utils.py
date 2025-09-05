import logging
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)
DEFAULT_DELETE_DELAY = 300  # 5 minutes

async def delete_message(context: ContextTypes.DEFAULT_TYPE):
    """Deletes a message."""
    try:
        await context.bot.delete_message(chat_id=context.job.chat_id, message_id=context.job.data)
        logger.info(f"自动删除了消息 {context.job.data} 在聊天 {context.job.chat_id}")
    except Exception as e:
        # 核心修正：在删除失败时，也打印出 chat_id 和 message_id，方便排查权限问题
        logger.warning(f"自动删除消息 {context.job.data} (chat: {context.job.chat_id}) 失败: {e}")

async def schedule_message_deletion(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int = DEFAULT_DELETE_DELAY):
    """Schedules a message to be deleted after a delay."""
    if not context.job_queue:
        logger.error("JobQueue not found in context. 无法安排消息删除。")
        return
    context.job_queue.run_once(delete_message, delay, data=message_id, chat_id=chat_id, name=f"delete_{chat_id}_{message_id}")
    logger.info(f"已计划在 {delay} 秒后删除消息 {message_id}")
