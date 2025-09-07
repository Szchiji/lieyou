import logging
import asyncpg
import os
from dotenv import load_dotenv
from telegram import User

# --- 初始化 ---
load_dotenv()
logger = logging.getLogger(__name__)
pool: asyncpg.Pool | None = None

# --- 数据库初始化 (最终版) ---
async def init_db():
    """
    初始化数据库连接池并创建所有表，以支持所有bot_handlers。
    """
    global pool
    if pool and not pool.is_closing():
        return

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is not set")

    try:
        pool = await asyncpg.create_pool(dsn=database_url, statement_cache_size=0)
        logger.info("数据库连接池已成功创建。")
        
        async with pool.acquire() as connection:
            logger.info("正在检查并创建数据表...")
            # 完整的数据表结构
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS users ( pkid SERIAL PRIMARY KEY, id BIGINT UNIQUE, username VARCHAR(255) UNIQUE, first_name VARCHAR(255), last_name VARCHAR(255), created_at TIMESTAMPTZ DEFAULT now());
                CREATE TABLE IF NOT EXISTS admins ( pkid SERIAL PRIMARY KEY, user_pkid INTEGER UNIQUE REFERENCES users(pkid) ON DELETE CASCADE, added_by_pkid INTEGER REFERENCES users(pkid) ON DELETE SET NULL, created_at TIMESTAMPTZ DEFAULT now());
                CREATE TABLE IF NOT EXISTS tags ( pkid SERIAL PRIMARY KEY, name VARCHAR(255) NOT NULL, type VARCHAR(50) NOT NULL, created_at TIMESTAMPTZ DEFAULT now(), UNIQUE(name, type));
                CREATE TABLE IF NOT EXISTS evaluations ( pkid SERIAL PRIMARY KEY, user_pkid INTEGER REFERENCES users(pkid) ON DELETE CASCADE, target_user_pkid INTEGER REFERENCES users(pkid) ON DELETE CASCADE, tag_pkid INTEGER REFERENCES tags(pkid) ON DELETE CASCADE, type VARCHAR(50) NOT NULL, created_at TIMESTAMPTZ DEFAULT now(), UNIQUE(user_pkid, target_user_pkid, tag_pkid));
                CREATE TABLE IF NOT EXISTS favorites ( pkid SERIAL PRIMARY KEY, user_pkid INTEGER REFERENCES users(pkid) ON DELETE CASCADE, target_user_pkid INTEGER REFERENCES users(pkid) ON DELETE CASCADE, created_at TIMESTAMPTZ DEFAULT now(), UNIQUE(user_pkid, target_user_pkid));
                CREATE TABLE IF NOT EXISTS settings ( key VARCHAR(255) PRIMARY KEY, value TEXT, updated_at TIMESTAMPTZ DEFAULT now());
            """)
            logger.info("数据表检查和创建完成。")

            # 确保 GOD 用户是管理员
            god_user_id_str = os.environ.get("GOD_USER_ID")
            if god_user_id_str:
                try:
                    god_user_id = int(god_user_id_str)
                    # 尝试找到GOD用户的pkid，无论他是否已在users表
                    user_pkid = await connection.fetchval("SELECT pkid FROM users WHERE id = $1", god_user_id)
                    if user_pkid:
                        await connection.execute("INSERT INTO admins (user_pkid) VALUES ($1) ON CONFLICT (user_pkid) DO NOTHING", user_pkid)
                        logger.info(f"已确保 GOD 用户 (ID: {god_user_id}) 是管理员。")
                except Exception as e:
                    logger.error(f"设置 GOD 用户时出错: {e}")

    except Exception as e:
        logger.critical(f"数据库初始化期间发生致命错误: {e}", exc_info=True)
        raise

# --- 数据库操作函数 (最终版) ---
async def get_pool():
    global pool
    if pool is None or pool.is_closing(): await init_db()
    return pool

async def db_execute(query, *args):
    conn_pool = await get_pool()
    async with conn_pool.acquire() as connection: return await connection.execute(query, *args)

async def db_fetch_all(query, *args):
    conn_pool = await get_pool()
    async with conn_pool.acquire() as connection: return await connection.fetch(query, *args)

async def db_fetch_one(query, *args):
    conn_pool = await get_pool()
    async with conn_pool.acquire() as connection: return await connection.fetchrow(query, *args)

async def db_fetch_val(query, *args):
    conn_pool = await get_pool()
    async with conn_pool.acquire() as connection: return await connection.fetchval(query, *args)

# --- 用户处理函数 ---
async def get_or_create_user(user: User) -> dict:
    if not user.username: raise ValueError("请先为您的Telegram账户设置一个用户名。")
    username_lower = user.username.lower()
    user_record = await db_fetch_one("SELECT * FROM users WHERE id = $1", user.id)
    if user_record:
        if user_record['username'] != username_lower or user_record['first_name'] != user.first_name:
            await db_execute("UPDATE users SET username = $1, first_name = $2, last_name = $3 WHERE id = $4", username_lower, user.first_name, user.last_name, user.id)
        return dict(await db_fetch_one("SELECT * FROM users WHERE id = $1", user.id))
    
    # 处理用户名可能被占用的情况
    user_record_by_name = await db_fetch_one("SELECT * FROM users WHERE username = $1", username_lower)
    if user_record_by_name:
        await db_execute("UPDATE users SET id = $1, first_name = $2, last_name = $3 WHERE username = $4", user.id, user.first_name, user.last_name, username_lower)
        return dict(await db_fetch_one("SELECT * FROM users WHERE id = $1", user.id))
        
    return dict(await db_fetch_one("INSERT INTO users (id, username, first_name, last_name) VALUES ($1, $2, $3, $4) RETURNING *", user.id, username_lower, user.first_name, user.last_name))

async def get_or_create_target(username: str) -> dict:
    username_lower = username.lower().strip('@')
    user_record = await db_fetch_one("SELECT * FROM users WHERE username = $1", username_lower)
    if user_record: return dict(user_record)
    # 只创建用户名，其他信息留空，等待用户本人启动机器人后填充
    return dict(await db_fetch_one("INSERT INTO users (username) VALUES ($1) ON CONFLICT (username) DO UPDATE SET username=EXCLUDED.username RETURNING *", username_lower))

# --- 权限和设置函数 ---
async def is_admin(user_id: int) -> bool:
    user_pkid = await db_fetch_val("SELECT pkid FROM users WHERE id = $1", user_id)
    if not user_pkid: return False
    return await db_fetch_val("SELECT 1 FROM admins WHERE user_pkid = $1", user_pkid) is not None

async def set_setting(key: str, value: str | None):
    if value is None:
        await db_execute("DELETE FROM settings WHERE key = $1", key)
    else:
        await db_execute("INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", key, value)

async def get_setting(key: str) -> str | None:
    return await db_fetch_val("SELECT value FROM settings WHERE key = $1", key)
