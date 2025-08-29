import asyncpg
import logging
from os import environ
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)
pool = None

async def init_pool():
    global pool
    if pool is None:
        try:
            pool = await asyncpg.create_pool(dsn=environ.get("DATABASE_URL"))
            logger.info("✅ 数据库连接池已成功初始化。")
        except Exception as e:
            logger.critical(f"❌ 致命错误: 数据库连接失败: {e}", exc_info=True)
            # 在这种情况下，我们可能希望应用程序无法启动
            raise e

@asynccontextmanager
async def db_transaction():
    if pool is None:
        await init_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn

async def create_tables():
    """创建所有必要的表（如果它们不存在）"""
    async with db_transaction() as conn:
        # 用户表: 存储用户ID和管理员状态，以及用户名
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY,
                username TEXT,
                is_admin BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        # 信誉档案表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reputation_profiles (
                username TEXT PRIMARY KEY,
                recommend_count INT DEFAULT 0,
                block_count INT DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        # 标签表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                id SERIAL PRIMARY KEY,
                tag_name TEXT NOT NULL,
                type TEXT NOT NULL, -- 'recommend' or 'block'
                UNIQUE(tag_name, type)
            );
        """)
        # 投票记录表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS votes (
                id SERIAL PRIMARY KEY,
                nominator_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
                nominee_username TEXT REFERENCES reputation_profiles(username) ON DELETE CASCADE,
                vote_type TEXT NOT NULL, -- 'recommend' or 'block'
                tag_id INT REFERENCES tags(id) ON DELETE SET NULL,
                created_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        # 收藏夹表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
                favorite_username TEXT REFERENCES reputation_profiles(username) ON DELETE CASCADE,
                UNIQUE(user_id, favorite_username)
            );
        """)
        # 系统设置表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        logger.info("✅ (启动流程) 所有数据表检查/创建完毕。")
