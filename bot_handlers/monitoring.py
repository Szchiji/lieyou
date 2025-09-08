import asyncio
import logging
from telegram import Bot

logger = logging.getLogger(__name__)

async def run_suspicion_monitor(bot: Bot):
    while True:
        try:
            # 可在此加入风控/反刷评价等逻辑
            await asyncio.sleep(300)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"monitor error: {e}")
            await asyncio.sleep(30)
