import logging
import asyncpg
from os import environ
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

POOL = None

async def init_pool():
    """初始化异步数据库连接池。"""
    global POOL
    if POOL:
        return
    try:
        POOL = await asyncpg.create_pool(
            dsn=environ.get("DATABASE_URL"),
            min_size=1,
            max_size=10
        )
        logger.info("✅ 异步数据库连接池初始化成功。")
    except Exception as e:
        logger.critical(f"❌ 数据库连接池初始化失败: {e}")
        raise

@asynccontextmanager
async def db_cursor():
    """提供一个异步数据库连接的上下文管理器。"""
    if not POOL:
        await init_pool() # 如果池不存在，则尝试初始化
    
    conn = None
    try:
        conn = await POOL.acquire()
        yield conn
    except Exception as e:
        logger.error(f"数据库操作中获取连接失败: {e}")
        raise
    finally:
        if conn:
            await POOL.release(conn)

async def create_tables():
    """检查并创建所有需要的表（完全异步）。"""
    async with db_cursor() as cur:
        try:
            # 创建 users 表
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY,
                    username VARCHAR(255),
                    full_name VARCHAR(255),
                    reputation INT DEFAULT 0,
                    is_admin BOOLEAN DEFAULT FALSE
                );
            """)
            
            # 尝试为旧表添加 full_name 列 (如果不存在)
            await cur.execute("""
                DO $$
                BEGIN
                    ALTER TABLE users ADD COLUMN full_name VARCHAR(255);
                    RAISE NOTICE '成功为 users 表添加 full_name 列。';
                EXCEPTION
                    WHEN duplicate_column THEN
                    RAISE NOTICE 'users 表的 full_name 列已存在，无需添加。';
                END
                $$;
            """)

            # 创建其他表
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id SERIAL PRIMARY KEY,
                    tag_name VARCHAR(255) UNIQUE NOT NULL,
                    type VARCHAR(50) NOT NULL CHECK (type IN ('recommend', 'block'))
                );
            """)
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS votes (
                    id SERIAL PRIMARY KEY,
                    nominator_id BIGINT REFERENCES users(id),
                    nominee_id BIGINT REFERENCES users(id),
                    tag_id INT REFERENCES tags(id),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(nominator_id, nominee_id, tag_id)
                );
            """)
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(id),
                    favorite_user_id BIGINT REFERENCES users(id),
                    UNIQUE(user_id, favorite_user_id)
                );
            """)
            logger.info("✅ 所有表都已成功检查/创建/更新。")
        except Exception as e:
            logger.error(f"❌ 创建或更新表时发生错误: {e}")
            raise
