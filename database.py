import asyncpg
import os
import logging
from dotenv import load_dotenv
from telegram import User

load_dotenv()
logger = logging.getLogger(__name__)
pool: asyncpg.Pool | None = None

async def init_db():
    """
    初始化数据库连接池并创建表（如果不存在）。
    此版本专门为 Neon.tech 数据库优化，是最终的安全版本。
    """
    global pool
    
    if pool is not None and not pool.is_closing():
        try:
            async with pool.acquire() as connection:
                await connection.fetchval("SELECT 1")
            logger.info("数据库连接池已存在且健康，跳过初始化。")
            return
        except Exception as e:
            logger.warning(f"检测到数据库连接池不健康: {e}。将强制关闭并重建。")
            await pool.close()
            pool = None

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.critical("DATABASE_URL 环境变量未设置！")
        raise ValueError("DATABASE_URL is not set")

    try:
        logger.info("正在为 Neon.tech 创建新的数据库连接池...")
        pool = await asyncpg.create_pool(
            dsn=database_url, 
            statement_cache_size=0,
            command_timeout=60 
        )
        logger.info("数据库连接池已成功创建 (Neon 优化模式)。")
        
        async with pool.acquire() as connection:
            logger.info("正在检查并创建数据表...")
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    pkid SERIAL PRIMARY KEY,
                    id BIGINT UNIQUE,
                    username VARCHAR(255) UNIQUE,
                    first_name VARCHAR(255),
                    last_name VARCHAR(255),
                    created_at TIMESTAMPTZ DEFAULT now()
                );
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    pkid SERIAL PRIMARY KEY, user_pkid INTEGER UNIQUE REFERENCES users(pkid) ON DELETE CASCADE,
                    added_by_pkid INTEGER REFERENCES users(pkid) ON DELETE SET NULL, created_at TIMESTAMPTZ DEFAULT now()
                );
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    pkid SERIAL PRIMARY KEY, name VARCHAR(255) NOT NULL, type VARCHAR(50) NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT now(), UNIQUE(name, type)
                );
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS evaluations (
                    pkid SERIAL PRIMARY KEY, user_pkid INTEGER REFERENCES users(pkid) ON DELETE CASCADE,
                    target_user_pkid INTEGER REFERENCES users(pkid) ON DELETE CASCADE, tag_pkid INTEGER REFERENCES tags(pkid) ON DELETE CASCADE,
                    type VARCHAR(50) NOT NULL, created_at TIMESTAMPTZ DEFAULT now(), UNIQUE(user_pkid, target_user_pkid, tag_pkid)
                );
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    pkid SERIAL PRIMARY KEY, user_pkid INTEGER REFERENCES users(pkid) ON DELETE CASCADE,
                    target_user_pkid INTEGER REFERENCES users(pkid) ON DELETE CASCADE, created_at TIMESTAMPTZ DEFAULT now(),
                    UNIQUE(user_pkid, target_user_pkid)
                );
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key VARCHAR(255) PRIMARY KEY, value TEXT, updated_at TIMESTAMPTZ DEFAULT now()
                );
            """)
            logger.info("数据表检查和创建完成。")
            
            god_user_id_str = os.environ.get("GOD_USER_ID")
            if god_user_id_str:
                try:
                    god_user_id = int(god_user_id_str)
                    god_user_record = await connection.fetchrow("SELECT pkid FROM users WHERE id = $1", god_user_id)
                    if god_user_record:
                        await connection.execute("INSERT INTO admins (user_pkid) VALUES ($1) ON CONFLICT (user_pkid) DO NOTHING", god_user_record['pkid'])
                        logger.info(f"已确保 GOD 用户 (ID: {god_user_id}) 是管理员。")
                except Exception as e:
                    logger.error(f"设置 GOD 用户时出错: {e}")

    except Exception as e:
        logger.critical(f"数据库初始化期间发生致命错误: {e}", exc_info=True)
        raise

async def get_pool():
    global pool
    if pool is None or pool.is_closing():
        await init_db()
    return pool

async def db_execute(query, *args):
    conn_pool = await get_pool()
    async with conn_pool.acquire() as connection:
        return await connection.execute(query, *args)

async def db_fetch_all(query, *args):
    conn_pool = await get_pool()
    async with conn_pool.acquire() as connection:
        return await connection.fetch(query, *args)

async def db_fetch_one(query, *args):
    conn_pool = await get_pool()
    async with conn_pool.acquire() as connection:
        return await connection.fetchrow(query, *args)

async def db_fetch_val(query, *args):
    conn_pool = await get_pool()
    async with conn_pool.acquire() as connection:
        return await connection.fetchval(query, *args)

async def get_or_create_user(user: User) -> dict:
    if not user.username:
        raise ValueError("请先为您的Telegram账户设置一个用户名。")
    username_lower = user.username.lower()
    
    query = """
    INSERT INTO users (id, username, first_name, last_name)
    VALUES ($1, $2, $3, $4)
    ON CONFLICT (id) DO UPDATE 
    SET username = EXCLUDED.username, first_name = EXCLUDED.first_name, last_name = EXCLUDED.last_name
    RETURNING *;
    """
    try:
        user_record = await db_fetch_one(query, user.id, username_lower, user.first_name, user.last_name)
    except asyncpg.UniqueViolationError: 
        await db_execute("UPDATE users SET id = $1, first_name = $2, last_name = $3 WHERE username = $4 AND id IS NULL",
                         user.id, user.first_name, user.last_name, username_lower)
        user_record = await db_fetch_one("SELECT * FROM users WHERE id = $1", user.id)

    return dict(user_record)


async def get_or_create_target(username: str) -> dict:
    username_lower = username.lower().strip('@')
    
    user_record = await db_fetch_one("SELECT * FROM users WHERE username = $1", username_lower)
    if not user_record:
        await db_execute("INSERT INTO users (username) VALUES ($1) ON CONFLICT (username) DO NOTHING", username_lower)
        user_record = await db_fetch_one("SELECT * FROM users WHERE username = $1", username_lower)

    return dict(user_record)

async def is_admin(user_id: int) -> bool:
    user_pkid = await db_fetch_val("SELECT pkid FROM users WHERE id = $1", user_id)
    if not user_pkid:
        return False
    admin_record = await db_fetch_one("SELECT 1 FROM admins WHERE user_pkid = $1", user_pkid)
    return admin_record is not None

async def get_setting(key: str) -> str | None:
    return await db_fetch_val("SELECT value FROM settings WHERE key = $1", key)

async def set_setting(key: str, value: str | None):
    if value is None:
        await db_execute("DELETE FROM settings WHERE key = $1", key)
    else:
        await db_execute(
            """
            INSERT INTO settings (key, value) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
            """,
            key, value
        )
