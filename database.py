import asyncpg
import logging
from os import environ

logger = logging.getLogger(__name__)
pool = None

async def init_pool():
    global pool
    if pool: return
    pool = await asyncpg.create_pool(
        dsn=environ.get("DATABASE_URL"),
        min_size=1,
        max_size=10,
        command_timeout=60,
    )
    logger.info("✅ 数据库连接池已成功初始化。")

async def create_tables():
    logger.info("✅ (启动流程) 正在检查并创建/迁移所有数据表...")
    await init_pool()
    async with pool.acquire() as conn:
        # users
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY,
                is_admin BOOLEAN DEFAULT FALSE
            );
        """)
    async with pool.acquire() as conn:
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN username TEXT;")
            logger.info("✅ (数据库迁移) 'users' 表已成功添加 'username' 字段。")
        except Exception as e:
            logger.warning(f"(数据库迁移) 添加 'username' 字段失败，可能已存在: {e}")
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reputation_profiles (
                username TEXT PRIMARY KEY,
                recommend_count INTEGER DEFAULT 0,
                block_count INTEGER DEFAULT 0
            );
        """)
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                id SERIAL PRIMARY KEY,
                tag_name TEXT NOT NULL,
                type TEXT NOT NULL,
                UNIQUE (tag_name, type)
            );
        """)
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS votes (
                id SERIAL PRIMARY KEY,
                nominator_id BIGINT NOT NULL,
                nominee_username TEXT NOT NULL,
                vote_type TEXT NOT NULL,
                tag_id INTEGER REFERENCES tags(id) ON DELETE SET NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                favorite_username TEXT NOT NULL,
                UNIQUE (user_id, favorite_username)
            );
        """)
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
    logger.info("✅ (启动流程) 所有数据表检查/创建/迁移完毕。")

# db_transaction 保持不变
from contextlib import asynccontextmanager
@asynccontextmanager
async def db_transaction():
    if not pool:
        await init_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn
