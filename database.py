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
    """最终的、绝对正确的数据库初始化程序。"""
    async with db_cursor() as cur:
        logger.info("正在执行最终的数据库结构审查与修正...")
        try:
            # --- 用户表：最终形态 ---
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY, username VARCHAR(255), full_name VARCHAR(255),
                    is_admin BOOLEAN DEFAULT FALSE
                );
            """)
            try: await cur.execute("ALTER TABLE users ADD COLUMN recommend_count INT DEFAULT 0;")
            except asyncpg.exceptions.DuplicateColumnError: pass
            try: await cur.execute("ALTER TABLE users ADD COLUMN block_count INT DEFAULT 0;")
            except asyncpg.exceptions.DuplicateColumnError: pass
            try: await cur.execute("ALTER TABLE users DROP COLUMN reputation;")
            except asyncpg.exceptions.UndefinedColumnError: pass

            # --- 标签表：最终形态（驱魔核心）---
            # 1. 先尝试删除可能存在的、错误的旧表
            await cur.execute("DROP TABLE IF EXISTS tags CASCADE;")
            logger.info("已移除可能存在错误的旧 `tags` 表，准备重建。")
            
            # 2. 创建100%正确的 `tags` 表
            await cur.execute("""
                CREATE TABLE tags (
                    id SERIAL PRIMARY KEY,
                    tag_name VARCHAR(255) UNIQUE NOT NULL,
                    type VARCHAR(50) NOT NULL CHECK (type IN ('recommend', 'block'))
                );
            """)
            logger.info("🎉 已成功创建 100% 正确的 `tags` 表！")

            # --- 投票表：最终形态 ---
            # 同样重建，以确保外键约束正确无误
            await cur.execute("DROP TABLE IF EXISTS votes CASCADE;")
            await cur.execute("""
                CREATE TABLE votes (
                    id SERIAL PRIMARY KEY,
                    nominator_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
                    nominee_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
                    tag_id INT REFERENCES tags(id) ON DELETE CASCADE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(nominator_id, nominee_id, tag_id)
                );
            """)
            logger.info("🎉 已成功创建 100% 正确的 `votes` 表！")

            # --- 收藏夹表：最终形态 ---
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    id SERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id),
                    favorite_user_id BIGINT REFERENCES users(id),
                    UNIQUE(user_id, favorite_user_id)
                );
            """)

            logger.info("✅✅✅ 所有数据库表都已达到最终的、完美的状态！")
        except Exception as e:
            logger.error(f"❌ 在最终的数据库修正过程中发生严重错误: {e}", exc_info=True)
            raise
