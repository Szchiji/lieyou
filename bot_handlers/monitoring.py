import logging
import asyncio
import os
from telegram import Bot
import database

logger = logging.getLogger(__name__)

async def run_suspicion_monitor(bot: Bot):
    """A task that runs periodically to check for suspicious activities."""
    admin_user_id = os.getenv("ADMIN_USER_ID")
    if not admin_user_id:
        logger.warning("ADMIN_USER_ID not set in .env. Suspicion monitor cannot send reports.")
        return

    logger.info("Suspicion monitor task started.")
    await asyncio.sleep(10) # Initial delay

    while True:
        try:
            logger.info("Running suspicion monitor check...")
            
            # --- 1. Check for "Shilling" (刷分) ---
            # Finds users who received more than 5 recommendations from the same person in the last 24 hours.
            shilling_query = """
                SELECT u_target.username as target_username, 
                       u_evaluator.username as evaluator_username, 
                       COUNT(e.pkid) as count
                FROM evaluations e
                JOIN users u_target ON e.target_user_pkid = u_target.pkid
                JOIN users u_evaluator ON e.evaluator_user_pkid = u_evaluator.pkid
                WHERE e.created_at >= NOW() - INTERVAL '24 hours' AND e.type = 'recommend'
                GROUP BY u_target.username, u_evaluator.username
                HAVING COUNT(e.pkid) > 5
                ORDER BY count DESC;
            """
            shilling_results = await database.db_fetch_all(shilling_query)
            if shilling_results:
                report = "⚠️ **可疑刷分行为警报** ⚠️\n\n"
                for res in shilling_results:
                    report += f" - @{res['evaluator_username']} 在24小时内推荐了 @{res['target_username']} **{res['count']}** 次。\n"
                await bot.send_message(admin_user_id, report)
                logger.warning(f"Suspicious shilling activity detected: {report}")

            # --- 2. Check for "Revenge Downvoting" (报复性差评) ---
            # Finds cases where A warns B within 10 minutes of B warning A.
            revenge_query = """
                SELECT u1.username as user1, u2.username as user2, e1.created_at as time1, e2.created_at as time2
                FROM evaluations e1
                JOIN evaluations e2 ON e1.evaluator_user_pkid = e2.target_user_pkid AND e1.target_user_pkid = e2.evaluator_user_pkid
                JOIN users u1 ON e1.evaluator_user_pkid = u1.pkid
                JOIN users u2 ON e2.evaluator_user_pkid = u2.pkid
                WHERE e1.type = 'warn' AND e2.type = 'warn'
                AND e1.created_at > e2.created_at
                AND (e1.created_at - e2.created_at) < INTERVAL '10 minutes'
                AND e1.created_at >= NOW() - INTERVAL '24 hours';
            """
            revenge_results = await database.db_fetch_all(revenge_query)
            if revenge_results:
                report = "⚠️ **可疑报复行为警报** ⚠️\n\n"
                for res in revenge_results:
                    report += f" - @{res['user1']} 在 @{res['user2']} 警告他/她之后10分钟内，也警告了对方。\n"
                await bot.send_message(admin_user_id, report)
                logger.warning(f"Suspicious revenge activity detected: {report}")

        except Exception as e:
            logger.error(f"Error in suspicion monitor: {e}", exc_info=True)
            
        # Run this check every hour
        await asyncio.sleep(3600)
