import asyncpg
import logging
from os import environ
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)
pool = None

async def init_pool():
    """Initializes the asynchronous database connection pool."""
    global pool
    if pool: return
    try:
        pool = await asyncpg.create_pool(dsn=environ.get("DATABASE_URL"), min_size=1, max_size=10)
        logger.info("✅ 异步数据库连接池初始化成功。")
    except Exception as e:
        logger.critical(f"❌ 数据库连接池初始化失败: {e}", exc_info=True)
        pool = None

@asynccontextmanager
async def db_transaction():
    """Provides a database transaction context manager."""
    if not pool:
        raise ConnectionError("数据库连接池未初始化。")
    async with pool.acquire() as connection:
        async with connection.transaction():
            logger.debug("开启新事务...")
            yield connection
            logger.debug("事务提交。")

async def create_tables():
    """
    Creates all necessary database tables *IF THEY DON'T EXIST*.
    This function is now safe to run on every startup.
    """
    logger.info("正在执行数据库结构审查...")
    async with db_transaction() as conn:
        # --- 【炸弹已拆除】 ---
        # 毁灭咒语 "DROP TABLE..." 已被彻底移除。
        # 现在，我们只创建尚不存在的表。
        
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            is_admin BOOLEAN NOT NULL DEFAULT FALSE
        );""")
        logger.info("  -> `users` 表结构审查完毕。")

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS reputation_profiles (
            username TEXT PRIMARY KEY,
            recommend_count INTEGER NOT NULL DEFAULT 0,
            block_count INTEGER NOT NULL DEFAULT 0
        );""")
        logger.info("  -> `reputation_profiles` 表结构审查完毕。")

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id SERIAL PRIMARY KEY,
            tag_name TEXT UNIQUE NOT NULL,
            type TEXT NOT NULL CHECK (type IN ('recommend', 'block'))
        );""")
        logger.info("  -> `tags` 表结构审查完毕。")

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS votes (
            id SERIAL PRIMARY KEY,
            nominator_id BIGINT NOT NULL,
            nominee_username TEXT NOT NULL,
            tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            UNIQUE(nominator_id, nominee_username, tag_id)
        );""")
        logger.info("  -> `votes` 表结构审查完毕。")
        
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            user_id BIGINT NOT NULL,
            favorite_username TEXT NOT NULL,
            PRIMARY KEY (user_id, favorite_username)
        );""")
        logger.info("  -> `favorites` 表结构审查完毕。")

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );""")
        # 只有在 settings 表第一次被创建时，才会尝试插入默认值。
        await conn.execute("INSERT INTO settings (key, value) VALUES ('auto_close_delay', '-1') ON CONFLICT DO NOTHING;")
        await conn.execute("INSERT INTO settings (key, value) VALUES ('leaderboard_cache_ttl', '300') ON CONFLICT DO NOTHING;")
        logger.info("  -> `settings` 表结构审查完毕。")
        
    logger.info("✅✅✅ 数据库结构已达到最终稳定状态！世界基石坚不可摧。")
