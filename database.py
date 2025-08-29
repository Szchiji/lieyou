import logging
import asyncpg
from os import environ
from contextlib import contextmanager

logger = logging.getLogger(__name__)

POOL = None

def init_pool():
    global POOL
    try:
        POOL = asyncpg.create_pool_sync(
            dsn=environ.get("DATABASE_URL"),
            min_size=1,
            max_size=10
        )
        logger.info("数据库连接池初始化成功。")
    except Exception as e:
        logger.critical(f"数据库连接池初始化失败: {e}")
        raise

@contextmanager
def db_cursor():
    if not POOL:
        raise ConnectionError("数据库连接池未初始化。")
    conn = None
    try:
        conn = POOL.acquire()
        yield conn
    finally:
        if conn:
            POOL.release(conn)

def create_tables():
    """
    检查并创建所有需要的表。
    核心修复：在 users 表中添加 full_name 字段。
    """
    with db_cursor() as cur:
        try:
            # 升级 users 表，添加 full_name 列
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY,
                    username VARCHAR(255),
                    full_name VARCHAR(255), -- 新增字段
                    reputation INT DEFAULT 0,
                    is_admin BOOLEAN DEFAULT FALSE
                );
            """)
            
            # 为了确保旧表也能更新，我们尝试添加列
            # 如果列已存在，会静默失败，不影响程序
            try:
                cur.execute("ALTER TABLE users ADD COLUMN full_name VARCHAR(255);")
                logger.info("成功为 users 表添加 full_name 列。")
            except asyncpg.exceptions.DuplicateColumnError:
                # 列已经存在，这是正常情况，无需操作
                pass

            cur.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id SERIAL PRIMARY KEY,
                    tag_name VARCHAR(255) UNIQUE NOT NULL,
                    type VARCHAR(50) NOT NULL CHECK (type IN ('recommend', 'block'))
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS votes (
                    id SERIAL PRIMARY KEY,
                    nominator_id BIGINT REFERENCES users(id),
                    nominee_id BIGINT REFERENCES users(id),
                    tag_id INT REFERENCES tags(id),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(nominator_id, nominee_id, tag_id)
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(id),
                    favorite_user_id BIGINT REFERENCES users(id),
                    UNIQUE(user_id, favorite_user_id)
                );
            """)
            logger.info("所有表都已成功检查/创建/更新。")
        except Exception as e:
            logger.error(f"创建或更新表时发生错误: {e}")
            raise
