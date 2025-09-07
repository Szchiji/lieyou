from telegram import Update
from telegram.ext import ContextTypes
import database

async def generate_my_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generates a personal reputation report for the user."""
    user_id = update.effective_user.id
    
    db_pool = await database.get_pool()
    async with db_pool.acquire() as conn:
        user_info = await conn.fetchrow(
            "SELECT pk_id, first_name, reputation FROM users WHERE user_id = $1", user_id
        )
        if not user_info:
            await update.message.reply_text("找不到您的用户信息。")
            return
            
        user_pkid = user_info['pk_id']
        
        evals_given = await conn.fetch(
            """
            SELECT t.tag_name, COUNT(e.pk_id) as count
            FROM evaluations e
            JOIN tags t ON e.tag_pkid = t.pk_id
            WHERE e.evaluator_user_pkid = $1
            GROUP BY t.tag_name
            """,
            user_pkid
        )
        
        evals_received = await conn.fetch(
            """
            SELECT t.tag_name, COUNT(e.pk_id) as count
            FROM evaluations e
            JOIN tags t ON e.tag_pkid = t.pk_id
            WHERE e.evaluated_user_pkid = $1
            GROUP BY t.tag_name
            """,
            user_pkid
        )

    report_text = f"你好, {user_info['first_name']}！这是您的声望报告：\n\n"
    report_text += f"**当前总声望**: {user_info['reputation']}\n\n"
    
    report_text += "**您收到的评价**:\n"
    if evals_received:
        for eval_item in evals_received:
            report_text += f"- {eval_item['tag_name']}: {eval_item['count']} 次\n"
    else:
        report_text += "- 暂无\n"
        
    report_text += "\n**您给出的评价**:\n"
    if evals_given:
        for eval_item in evals_given:
            report_text += f"- {eval_item['tag_name']}: {eval_item['count']} 次\n"
    else:
        report_text += "- 暂无\n"

    await update.message.reply_text(report_text, parse_mode='Markdown')
