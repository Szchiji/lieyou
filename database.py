import asyncpg
import os
import logging
from dotenv import load_dotenv
from telegram import User

# 加载环境变量
load_dotenv()

logger = logging.getLogger(__name__)

# 全局连接池变量
pool: asyncpg.Pool | None = None

async def init_db():
    """
    初始化数据库连接池并创建表（如果不存在）。
    此版本专门为 Neon.tech 数据库优化。
    """
    global pool
    
    # 如果连接池已存在且未关闭，先关闭它，确保我们总是用新配置创建
    if pool is not None and not pool.is_closing():
        logger.warning("检测到已存在的连接池，将强制关闭以应用新配置。")
        await pool.close()
        pool = None

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.critical("DATABASE_URL 环境变量未设置！")
        raise ValueError("DATABASE_URL is not set")

    try:
        # --- 针对 Neon.tech 的关键优化 ---
        # 1. statement_cache_size=0 禁用预编译指令缓存，避免 schema a变化导致的问题
        # 2. command_timeout 设置一个命令超时，避免因 Neon 休眠唤醒导致长时间卡顿
        logger.info("正在为 Neon.tech 创建新的数据库连接池...")
        pool = await asyncpg.create_pool(
            dsn=database_url, 
            statement_cache_size=0,
            command_timeout=60 
        )
        logger.info("数据库连接池已成功创建 (Neon 优化模式)。")
        
        async with pool.acquire() as connection:
            logger.info("正在检查并创建数据表...")
            # 为了绝对保险，我们先删除所有表，再重建
            logger.warning("!!! 正在执行一次性爆破操作以确保数据库结构最新 !!!")
            await connection.execute("DROP TABLE IF EXISTS evaluations CASCADE;")
            await connection.execute("DROP TABLE IF EXISTS favorites CASCADE;")
            await connection.execute("DROP TABLE IF EXISTS admins CASCADE;")
            await connection.execute("DROP TABLE IF EXISTS users CASCADE;")
            await connection.execute("DROP TABLE IF EXISTS tags CASCADE;")
            await connection.execute("DROP TABLE IF EXISTS settings CASCADE;")
            logger.warning("!!! 爆破操作完成。")

            # 创建 users 表
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    pkid SERIAL PRIMARY KEY,
                    id BIGINT UNIQUE NOT NULL,
                    username VARCHAR(255) UNIQUE,
                    first_name VARCHAR(255),
                    last_name VARCHAR(255),
                    created_at TIMESTAMPTZ DEFAULT now()
                );
            """)
            # ... (其他 CREATE TABLE 语句保持不变) ...
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    pkid SERIAL PRIMARY KEY,
                    user_pkid INTEGER UNIQUE REFERENCES users(pkid) ON DELETE CASCADE,
                    added_by_pkid INTEGER REFERENCES users(pkid) ON DELETE SET NULL,
                    created_at TIMESTAMPTZ DEFAULT now()
                );
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    pkid SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    type VARCHAR(50) NOT NULL, -- 'recommend' or 'block'
                    created_at TIMESTAMPTZ DEFAULT now(),
                    UNIQUE(name, type)
                );
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS evaluations (
                    pkid SERIAL PRIMARY KEY,
                    user_pkid INTEGER REFERENCES users(pkid) ON DELETE CASCADE,
                    target_user_pkid INTEGER REFERENCES users(pkid) ON DELETE CASCADE,
                    tag_pkid INTEGER REFERENCES tags(pkid) ON DELETE CASCADE,
                    type VARCHAR(50) NOT NULL, -- 'recommend' or 'block'
                    created_at TIMESTAMPTZ DEFAULT now(),
                    UNIQUE(user_pkid, target_user_pkid, tag_pkid)
                );
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    pkid SERIAL PRIMARY KEY,
                    user_pkid INTEGER REFERENCES users(pkid) ON DELETE CASCADE,
                    target_user_pkid INTEGER REFERENCES users(pkid) ON DELETE CASCADE,
                    created_at TIMESTAMPTZ DEFAULT now(),
                    UNIQUE(user_pkid, target_user_pkid)
                );
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key VARCHAR(255) PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMPTZ DEFAULT now()
                );
            """)
            logger.info("数据表已使用全新结构创建完成。")
            
            # 检查并设置 GOD_USER_ID
            god_user_id_str = os.environ.get("GOD_USER_ID")
            if god_user_id_str:
                try:
                    god_user_id = int(god_user_id_str)
                    god_user_record = await connection.fetchrow("SELECT pkid FROM users WHERE id = $1", god_user_id)
                    if god_user_record:
                        await connection.execute("INSERT INTO admins (user_pkid) VALUES ($1) ON CONFLICT (user_pkid) DO NOTHING", god_user_record['pkid'])
                        logger.info(f"已确保 GOD 用户 (ID: {god_user_id}) 是管理员。")
                    else:
                        logger.warning(f"GOD_USER_ID (ID: {god_user_id}) 在 users 表中未找到。")
                except Exception as e:
                    logger.error(f"设置 GOD 用户时出错: {e}")

    except Exception as e:
        logger.critical(f"数据库初始化期间发生致命错误: {e}", exc_info=True)
        raise

# ... (get_pool, db_execute 等其他函数保持不变) ...
async def get_pool():
    global pool
    if pool is None or pool.is_closing(): # 增加一个 is_closing 的判断
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
        raise ValueError("用户必须设置用户名才能使用此机器人。")
    username_lower = user.username.lower()
    user_record = await db_fetch_one("SELECT * FROM users WHERE id = $1", user.id)
    if user_record:
        if user_record['username'] != username_lower or user_record['first_name'] != user.first_name or user_record['last_name'] != user.last_name:
            user_record = await db_fetch_one("UPDATE users SET username = $1, first_name = $2, last_name = $3 WHERE id = $4 RETURNING *", username_lower, user.first_name, user.last_name, user.id)
    else:
        try:
            user_record = await db_fetch_one("INSERT INTO users (id, username, first_name, last_name) VALUES ($1, $2, $3, $4) RETURNING *", user.id, username_lower, user.first_name, user.last_name)
        except asyncpg.UniqueViolationError:
            user_record = await db_fetch_one("SELECT * FROM users WHERE username = $1", username_lower)
            if user_record:
                 user_record = await db_fetch_one("SELECT * FROM users WHERE id = $1", user.id)
            else:
                raise
    return dict(user_record)

async def get_or_create_target(username: str) -> dict:
    username_lower = username.lower()
    user_record = await db_fetch_one("SELECT * FROM users WHERE username = $1", username_lower)
    if not user_record:
        user_record = await db_fetch_one("INSERT INTO users (username) VALUES ($1) ON CONFLICT (username) DO UPDATE SET username=EXCLUDED.username RETURNING *", username_lower)
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
        await db_execute("""INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""", key, value)
