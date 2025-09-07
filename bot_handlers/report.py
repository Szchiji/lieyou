import logging
from telegram import Update
from telegram.ext import ContextTypes
import database
from .reputation import get_reputation_stats # 导入我们新的动态声望计算函数

logger = logging.getLogger(__name__)

async def generate_my_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Generates a personal reputation report for the user,
    adapted for the new dynamic reputation system.
    """
    user = update.effective_user
    logger.info(f"User {user.id} requested a personal report.")

    # 获取用户在我们数据库中的信息
    user_record = await database.db_fetch_one(
        "SELECT pkid, first_name FROM users WHERE id = $1", user.id
    )

    if not user_record:
        # 如果用户不存在于数据库（例如，从未/start过），先创建用户
        await database.get_or_create_user(user)
        user_record = await database.db_fetch_one(
            "SELECT pkid, first_name FROM users WHERE id = $1", user.id
        )
        if not user_record:
            await update.message.reply_text("无法创建或找到您的用户信息，请稍后再试。")
            return

    user_pkid = user_record['pkid']

    # 1. 使用新的动态函数计算当前声望
    stats = await get_reputation_stats(user_pkid)
    current_reputation_score = stats['reputation_score']

    # 2. 查询用户收到的评价 (使用正确的列名: target_user_pkid, pkid, name)
    evals_received = await database.db_fetch_all(
        """
        SELECT t.name, COUNT(e.pkid) as count
        FROM evaluations e
        JOIN tags t ON e.tag_pkid = t.pkid
        WHERE e.target_user_pkid = $1
        GROUP BY t.name
        """,
        user_pkid
    )
    
    # 3. 查询用户给出的评价 (使用正确的列名: evaluator_user_pkid, pkid, name)
    evals_given = await database.db_fetch_all(
        """
        SELECT t.name, COUNT(e.pkid) as count
        FROM evaluations e
        JOIN tags t ON e.tag_pkid = t.pkid
        WHERE e.evaluator_user_pkid = $1
        GROUP BY t.name
        """,
        user_pkid
    )

    # 构建报告文本
    report_text = f"你好, {user_record['first_name']}！这是您的声望报告：\n\n"
    report_text += f"**🔥 当前动态声望**: {current_reputation_score}\n\n"
    
    report_text += "**您收到的评价**:\n"
    if evals_received:
        for eval_item in evals_received:
            report_text += f"- {eval_item['name']}: {eval_item['count']} 次\n"
    else:
        report_text += "  - 暂无\n"
        
    report_text += "\n**您给出的评价**:\n"
    if evals_given:
        for eval_item in evals_given:
            report_text += f"- {eval_item['name']}: {eval_item['count']} 次\n"
    else:
        report_text += "  - 暂无\n"

    await update.message.reply_text(report_text, parse_mode='Markdown')
