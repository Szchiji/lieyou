import asyncpg
import logging
from os import environ
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# 全局数据库连接池
pool = None

async def get_pool():
    """获取或创建数据库连接池"""
    global pool
    if pool is None:
        try:
            pool = await asyncpg.create_pool(
                dsn=environ.get("DATABASE_URL"),
                min_size=1,
                max_size=10
            )
            logger.info("数据库连接池创建成功。")
        except Exception as e:
            logger.critical(f"无法连接到数据库: {e}")
            pool = None
    return pool

async def init_db():
    """初始化数据库，创建所有需要的表"""
    conn = None
    try:
        pool = await get_pool()
        if not pool:
            logger.error("数据库连接池不可用，无法初始化数据库。")
            return
            
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    is_admin BOOLEAN DEFAULT FALSE,
                    last_active_at TIMESTAMPTZ DEFAULT (now() AT TIME ZONE 'utc'),
                    created_at TIMESTAMPTZ DEFAULT (now() AT TIME ZONE 'utc')
                );
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    type TEXT NOT NULL CHECK (type IN ('recommend', 'block')),
                    created_at TIMESTAMPTZ DEFAULT (now() AT TIME ZONE 'utc')
                );
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS votes (
                    id SERIAL PRIMARY KEY,
                    voter_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    target_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                    message_id BIGINT,
                    chat_id BIGINT,
                    created_at TIMESTAMPTZ DEFAULT (now() AT TIME ZONE 'utc'),
                    UNIQUE (voter_user_id, target_user_id, tag_id)
                );
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    target_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    UNIQUE (user_id, target_user_id)
                );
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMPTZ DEFAULT (now() AT TIME ZONE 'utc')
                );
            """)
            logger.info("数据库表结构检查/初始化完成。")

            # 确保创建者是管理员
            creator_id_str = environ.get("CREATOR_ID")
            if creator_id_str:
                try:
                    creator_id = int(creator_id_str)
                    await conn.execute(
                        "INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE",
                        creator_id
                    )
                    logger.info(f"已确保创建者 (ID: {creator_id}) 的管理员权限。")
                except ValueError:
                    logger.error("CREATOR_ID 格式错误，无法设置初始管理员。")

    except Exception as e:
        logger.error(f"数据库初始化过程中发生错误: {e}")
    finally:
        if conn:
            await pool.release(conn)

async def db_execute(query, *args):
    """执行一个SQL命令 (INSERT, UPDATE, DELETE)"""
    pool = await get_pool()
    if not pool: return
    async with pool.acquire() as conn:
        await conn.execute(query, *args)

async def db_fetch_one(query, *args):
    """获取一行查询结果"""
    pool = await get_pool()
    if not pool: return None
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)

async def db_fetch_all(query, *args):
    """获取所有查询结果"""
    pool = await get_pool()
    if not pool: return []
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)

async def db_fetchval(query, *args):
    """获取结果中的单个值"""
    pool = await get_pool()
    if not pool: return None
    async with pool.acquire() as conn:
        return await conn.fetchval(query, *args)

@asynccontextmanager
async def db_transaction():
    """提供一个数据库事务上下文"""
    pool = await get_pool()
    if not pool:
        raise ConnectionError("数据库连接池不可用")
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn

async def update_user_activity(user_id: int, username: str, first_name: str):
    """更新用户信息和最后活跃时间"""
    await db_execute(
        """
        INSERT INTO users (id, username, first_name, last_active_at)
        VALUES ($1, $2, $3, now() AT TIME ZONE 'utc')
        ON CONFLICT (id) DO UPDATE SET
            username = $2,
            first_name = $3,
            last_active_at = now() AT TIME ZONE 'utc';
        """,
        user_id, username, first_name
    )

async def is_admin(user_id: int) -> bool:
    """检查用户是否为管理员"""
    creator_id_str = environ.get("CREATOR_ID")
    if creator_id_str and user_id == int(creator_id_str):
        return True
    
    user = await db_fetch_one("SELECT is_admin FROM users WHERE id = $1", user_id)
    return user['is_admin'] if user else False

async def get_setting(key: str, default: str = None) -> str:
    """从数据库获取设置项"""
    value = await db_fetchval("SELECT value FROM settings WHERE key = $1", key)
    return value if value is not None else default

async def set_setting(key: str, value: str):
    """在数据库中设置或更新一个设置项"""
    await db_execute(
        """
        INSERT INTO settings (key, value, updated_at) VALUES ($1, $2, now() AT TIME ZONE 'utc')
        ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = now() AT TIME ZONE 'utc';
        """,
        key, value
    )
