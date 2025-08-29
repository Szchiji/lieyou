import logging
import asyncpg
from os import environ
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

POOL = None

async def init_pool():
    global POOL
    if POOL: return
    try:
        POOL = await asyncpg.create_pool(dsn=environ.get("DATABASE_URL"))
        logger.info("✅ 异步数据库连接池初始化成功。")
    except Exception as e:
        logger.critical(f"❌ 数据库连接池初始化失败: {e}", exc_info=True)
        raise

@asynccontextmanager
async def db_cursor():
    if not POOL: await init_pool()
    conn = None
    try:
        conn = await POOL.acquire()
        yield conn
    except Exception as e:
        logger.error(f"数据库操作中发生错误: {e}", exc_info=True)
        raise
    finally:
        if conn: await POOL.release(conn)

async def create_tables():
    """检查、创建并迁移所有需要的表，实现“双轨制”。"""
    async with db_cursor() as cur:
        try:
            # 1. 创建或更新 users 表，加入新字段
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY, username VARCHAR(255), full_name VARCHAR(255),
                    recommend_count INT DEFAULT 0,
                    block_count INT DEFAULT 0,
                    is_admin BOOLEAN DEFAULT FALSE
                );
            """)
            # 2. 尝试添加新列（如果不存在）
            try:
                await cur.execute("ALTER TABLE users ADD COLUMN recommend_count INT DEFAULT 0;")
                logger.info("成功为 users 表添加 recommend_count 列。")
            except asyncpg.exceptions.DuplicateColumnError: pass
            try:
                await cur.execute("ALTER TABLE users ADD COLUMN block_count INT DEFAULT 0;")
                logger.info("成功为 users 表添加 block_count 列。")
            except asyncpg.exceptions.DuplicateColumnError: pass
            
            # 3. 尝试删除旧的 reputation 列（如果存在）
            try:
                await cur.execute("ALTER TABLE users DROP COLUMN reputation;")
                logger.info("🎉 成功！已彻底移除旧的 reputation 列。")
            except asyncpg.exceptions.UndefinedColumnError: pass

            # --- 其他表保持不变 ---
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id SERIAL PRIMARY KEY, tag_name VARCHAR(255) UNIQUE NOT NULL,
                    type VARCHAR(50) NOT NULL CHECK (type IN ('recommend', 'block'))
                );
            """)
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS votes (
                    id SERIAL PRIMARY KEY, nominator_id BIGINT REFERENCES users(id),
                    nominee_id BIGINT REFERENCES users(id), tag_id INT REFERENCES tags(id),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(nominator_id, nominee_id, tag_id)
                );
            """)
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    id SERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id),
                    favorite_user_id BIGINT REFERENCES users(id),
                    UNIQUE(user_id, favorite_user_id)
                );
            """)
            logger.info("✅ 所有表都已成功检查/创建/更新为“双轨制”。")
        except Exception as e:
            logger.error(f"❌ 创建或更新表时发生错误: {e}", exc_info=True)
            raise
