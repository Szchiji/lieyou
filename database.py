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
        await init_pool()
    
    conn = None
    try:
        conn = await POOL.acquire()
        yield conn
    except Exception as e:
        logger.error(f"数据库操作中发生错误: {e}")
        raise
    finally:
        if conn:
            await POOL.release(conn)

async def create_tables():
    """检查、创建并迁移所有需要的表（完全异步）。"""
    async with db_cursor() as cur:
        try:
            # --- 用户表 ---
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY, username VARCHAR(255), full_name VARCHAR(255),
                    reputation INT DEFAULT 0, is_admin BOOLEAN DEFAULT FALSE
                );
            """)
            try:
                await cur.execute("ALTER TABLE users ADD COLUMN full_name VARCHAR(255);")
            except asyncpg.exceptions.DuplicateColumnError: pass

            # --- 标签表 ---
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id SERIAL PRIMARY KEY, tag_name VARCHAR(255) UNIQUE NOT NULL,
                    type VARCHAR(50) NOT NULL CHECK (type IN ('recommend', 'block'))
                );
            """)
            
            # --- 核心修复 2：为 tags 表执行“更名手术” ---
            try:
                # 检查是否存在错误的 `tag_type` 列，并将其更名为正确的 `tag_name`
                await cur.execute("ALTER TABLE tags RENAME COLUMN tag_type TO tag_name;")
                logger.info("🎉 成功！已将历史遗留的 `tags.tag_type` 字段更名为 `tags.tag_name`。")
            except asyncpg.exceptions.UndefinedColumnError:
                pass # 字段名已经是正确的，无需操作
            except asyncpg.exceptions.DuplicateColumnError:
                pass # 正确的字段已存在，无需操作


            # --- 投票表 ---
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS votes (
                    id SERIAL PRIMARY KEY, nominator_id BIGINT REFERENCES users(id),
                    nominee_id BIGINT REFERENCES users(id), tag_id INT REFERENCES tags(id),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(nominator_id, nominee_id, tag_id)
                );
            """)
            
            # --- 核心修复 1：为 votes 表执行“更名手术” ---
            try:
                await cur.execute("ALTER TABLE votes RENAME COLUMN target_id TO tag_id;")
                logger.info("🎉 成功！已将历史遗留的 `votes.target_id` 字段更名为 `votes.tag_id`。")
            except asyncpg.exceptions.UndefinedColumnError:
                pass # 字段名已经是正确的，无需操作

            # --- 收藏夹表 ---
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    id SERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id),
                    favorite_user_id BIGINT REFERENCES users(id),
                    UNIQUE(user_id, favorite_user_id)
                );
            """)

            logger.info("✅ 所有表都已成功检查/创建/更新。")
        except Exception as e:
            logger.error(f"❌ 创建或更新表时发生错误: {e}")
            raise
