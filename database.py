import asyncpg
import logging
from os import environ
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)
pool = None

async def init_pool():
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
    """
    提供一个数据库事务的上下文管理器。
    这是本次修复的核心，确保数据写入的原子性。
    """
    if not pool:
        raise ConnectionError("数据库连接池未初始化。")
    async with pool.acquire() as connection:
        async with connection.transaction():
            logger.debug("开启新事务...")
            yield connection
            logger.debug("事务提交。")

async def create_tables():
    """创建所有必要的数据库表。"""
    logger.info("正在执行最终的数据库结构审查与重建...")
    async with db_transaction() as conn:
        await conn.execute("DROP TABLE IF EXISTS votes, tags, reputation_profiles, users, favorites, settings CASCADE;")
        logger.info("已移除所有旧的核心数据表，准备重建为“万物信誉系统”。")
        
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS reputation_profiles (
            username TEXT PRIMARY KEY,
            recommend_count INTEGER NOT NULL DEFAULT 0,
            block_count INTEGER NOT NULL DEFAULT 0
        );""")
        logger.info("🎉 已成功创建核心的 `reputation_profiles` 表！")

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id SERIAL PRIMARY KEY,
            tag_name TEXT UNIQUE NOT NULL,
            type TEXT NOT NULL CHECK (type IN ('recommend', 'block'))
        );""")

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS votes (
            id SERIAL PRIMARY KEY,
            nominator_id BIGINT NOT NULL,
            nominee_username TEXT NOT NULL,
            tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            UNIQUE(nominator_id, nominee_username, tag_id)
        );""")
        logger.info("🎉 已成功创建适配“符号系统”的 `votes` 表！")

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            is_admin BOOLEAN NOT NULL DEFAULT FALSE
        );""")
        
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            user_id BIGINT NOT NULL,
            favorite_username TEXT NOT NULL,
            PRIMARY KEY (user_id, favorite_username)
        );""")
        logger.info("🎉 已成功重建“符号收藏夹” (`favorites`) 表！")

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );""")
        await conn.execute("INSERT INTO settings (key, value) VALUES ('auto_close_delay', '-1') ON CONFLICT DO NOTHING;")
        await conn.execute("INSERT INTO settings (key, value) VALUES ('leaderboard_cache_ttl', '300') ON CONFLICT DO NOTHING;")
        logger.info("🎉 已成功创建并初始化 `settings` 表！")
        
    logger.info("✅✅✅ 所有数据库表都已达到最终的、完美的“万物信誉系统”状态！")
