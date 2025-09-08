import asyncio
import logging
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

async def monitor_tick(context: ContextTypes.DEFAULT_TYPE):
    """
    定时任务：一次执行一轮监控逻辑，由 JobQueue 周期调度。
    使用 context.bot 访问 Bot。
    """
    try:
        bot = context.bot
        # TODO: 在这里实现一次监控逻辑
        # 例如：检查可疑评分、清理过期任务、统计上报等
        # logger.debug("monitor tick")
        pass
    except Exception as e:
        logger.error(f"monitor_tick error: {e}")

async def run_monitor_background(bot, interval: int = 300):
    """
    兜底方案：当 JobQueue 不可用时，使用后台 asyncio 任务周期性调用 monitor_tick。
    会在应用关闭时被取消（见 main.post_shutdown）。
    """
    class _Ctx:
        def __init__(self, bot):
            self.bot = bot

    while True:
        try:
            await monitor_tick(_Ctx(bot))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"monitor loop error: {e}")
        await asyncio.sleep(interval)
