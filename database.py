import asyncpg
import logging
from os import environ
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

pool = None

async def get_pool():
    global pool
    if pool is None:
        try:
            # --- 核心修正：强制禁用语句缓存 ---
            # statement_cache_size=0 告诉数据库驱动不要缓存任何查询计划。
            # 这会彻底解决 InvalidCachedStatementError 的问题。
            pool = await asyncpg.create_pool(
                dsn=environ.get("DATABASE_URL"), 
                min_size=1, 
                max_size=10,
                statement_cache_size=0
            )
            logger.info("数据库连接池创建成功（已禁用语句缓存）。")
        except Exception as e:
            logger.critical(f"无法连接到数据库: {e}")
            pool = None
    return pool

async def init_db():
    """初始化数据库，创建所有需要的表。"""
    pool = await get_pool()
    if not pool:
        logger.error("数据库连接池不可用，无法初始化数据库。")
        return
        
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        pkid SERIAL PRIMARY KEY,
                        id BIGINT UNIQUE,
                        username TEXT UNIQUE,
                        first_name TEXT,
                        is_admin BOOLEAN DEFAULT FALSE,
                        last_active_at TIMESTAMPTZ DEFAULT (now() AT TIME ZONE 'utc'),
                        created_at TIMESTAMPTZ DEFAULT (now() AT TIME ZONE 'utc')
                    );
                """)
                id_is_not_null = await conn.fetchval("""
                    SELECT attnotnull FROM pg_attribute 
                    WHERE attrelid = 'users'::regclass AND attname = 'id';
                """)
                if id_is_not_null:
                    logger.info("检测到 'users.id' 的 NOT NULL 约束，正在移除...")
                    await conn.execute("ALTER TABLE users ALTER COLUMN id DROP NOT NULL;")
                    logger.info("约束移除成功。")

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS tags (
                        id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL, type TEXT NOT NULL CHECK (type IN ('recommend', 'block')),
                        created_at TIMESTAMPTZ DEFAULT (now() AT TIME ZONE 'utc'));
                """)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS votes (
                        id SERIAL PRIMARY KEY, voter_user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                        target_user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                        tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE, message_id BIGINT, chat_id BIGINT,
                        created_at TIMESTAMPTZ DEFAULT (now() AT TIME ZONE 'utc'),
                        UNIQUE (voter_user_pkid, target_user_pkid, tag_id));
                """)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS favorites (
                        id SERIAL PRIMARY KEY, user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                        target_user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                        UNIQUE (user_pkid, target_user_pkid));
                """)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMPTZ DEFAULT (now() AT TIME ZONE 'utc'));
                """)
                logger.info("数据库表结构检查/创建/修正完成。")

                creator_id_str = environ.get("CREATOR_ID")
                if creator_id_str:
                    creator_id = int(creator_id_str)
                    await conn.execute(
                        "INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE WHERE users.id IS NOT NULL;",
                        creator_id
                    )
                    logger.info(f"已确保创建者 (ID: {creator_id}) 的管理员权限。")
            except Exception as e:
                logger.error(f"数据库初始化过程中发生错误: {e}", exc_info=True)
                raise

async def db_execute(query, *args):
    pool = await get_pool();
    if not pool: return
    async with pool.acquire() as conn: await conn.execute(query, *args)

async def db_fetch_one(query, *args):
    pool = await get_pool();
    if not pool: return None
    async with pool.acquire() as conn: return await conn.fetchrow(query, *args)

async def db_fetch_all(query, *args):
    pool = await get_pool();
    if not pool: return []
    async with pool.acquire() as conn: return await conn.fetch(query, *args)

async def db_fetchval(query, *args):
    pool = await get_pool();
    if not pool: return None
    async with pool.acquire() as conn: return await conn.fetchval(query, *args)

async def get_or_create_user(user_id: int = None, username: str = None, first_name: str = None) -> dict:
    if not user_id and not username: return None
    if user_id:
        user = await db_fetch_one("SELECT * FROM users WHERE id = $1", user_id)
        if user:
            await db_execute("UPDATE users SET username = $2, first_name = $3, last_active_at = now() AT TIME ZONE 'utc' WHERE id = $1", user_id, username, first_name)
            return await db_fetch_one("SELECT * FROM users WHERE id = $1", user_id)
    if username:
        user = await db_fetch_one("SELECT * FROM users WHERE username = $1", username)
        if user:
            if user_id and not user['id']:
                 await db_execute("UPDATE users SET id = $1 WHERE username = $2", user_id, username)
            return await db_fetch_one("SELECT * FROM users WHERE username = $1", username)
    try:
        if user_id:
            return await db_fetch_one("INSERT INTO users (id, username, first_name) VALUES ($1, $2, $3) RETURNING *", user_id, username, first_name)
        elif username:
            return await db_fetch_one("INSERT INTO users (username, first_name) VALUES ($1, $2) ON CONFLICT (username) DO UPDATE SET first_name = $2 RETURNING *", username, first_name or username)
    except asyncpg.UniqueViolationError as e:
        logger.warning(f"并发插入冲突，重新查询用户: {e}")
        return await get_or_create_user(user_id, username, first_name)
    return None

async def is_admin(user_id: int) -> bool:
    if not user_id: return False
    creator_id_str = environ.get("CREATOR_ID")
    if creator_id_str and user_id == int(creator_id_str): return True
    user = await db_fetch_one("SELECT is_admin FROM users WHERE id = $1", user_id)
    return user['is_admin'] if user else False

async def get_setting(key: str, default: str = None) -> str:
    value = await db_fetchval("SELECT value FROM settings WHERE key = $1", key)
    return value if value is not None else default

async def set_setting(key: str, value: str):
    await db_execute("INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = $2", key, value)
