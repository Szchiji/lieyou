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
        pool = await asyncpg.create_pool(
            dsn=environ.get("DATABASE_URL"),
            min_size=1,
            max_size=10,
            command_timeout=60,
        )
        logger.info("✅ 数据库连接池已成功初始化。")
    except Exception as e:
        logger.critical(f"❌ 数据库连接池初始化失败: {e}", exc_info=True)
        raise

@asynccontextmanager
async def db_transaction():
    if not pool:
        await init_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn

async def create_tables():
    logger.info("✅ (启动流程) 正在检查并创建/迁移所有数据表...")
    async with db_transaction() as conn:
        # --- users 表 ---
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY,
                is_admin BOOLEAN DEFAULT FALSE
            );
        """)
        # --- “进化法则”：为 users 表添加 username 字段 ---
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN username TEXT;")
            logger.info("✅ (数据库迁移) 'users' 表已成功添加 'username' 字段。")
        except asyncpg.exceptions.DuplicateColumnError:
            # 字段已存在，静默处理
            pass

        # --- reputation_profiles 表 ---
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reputation_profiles (
                username TEXT PRIMARY KEY,
                recommend_count INTEGER DEFAULT 0,
                block_count INTEGER DEFAULT 0
            );
        """)

        # --- tags 表 ---
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                id SERIAL PRIMARY KEY,
                tag_name TEXT NOT NULL,
                type TEXT NOT NULL, -- 'recommend' or 'block'
                UNIQUE (tag_name, type)
            );
        """)
        
        # --- votes 表 ---
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS votes (
                id SERIAL PRIMARY KEY,
                nominator_id BIGINT NOT NULL,
                nominee_username TEXT NOT NULL,
                vote_type TEXT NOT NULL, -- 'recommend' or 'block'
                tag_id INTEGER REFERENCES tags(id) ON DELETE SET NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # --- favorites 表 ---
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                favorite_username TEXT NOT NULL,
                UNIQUE (user_id, favorite_username)
            );
        """)

        # --- settings 表 ---
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
    logger.info("✅ (启动流程) 所有数据表检查/创建/迁移完毕。")
