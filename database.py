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
    此版本增加了 menu_buttons 表。
    """
    global pool
    if pool and not pool.is_closing(): return

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is not set")

    try:
        pool = await asyncpg.create_pool(dsn=database_url, statement_cache_size=0)
        logger.info("数据库连接池已成功创建。")
        
        async with pool.acquire() as connection:
            logger.info("正在检查并创建数据表...")
            # 创建 users, admins, tags, evaluations, favorites, settings 表（代码与上一版相同，此处省略以保持简洁）
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS users ( pkid SERIAL PRIMARY KEY, id BIGINT UNIQUE, username VARCHAR(255) UNIQUE, first_name VARCHAR(255), last_name VARCHAR(255), created_at TIMESTAMPTZ DEFAULT now());
                CREATE TABLE IF NOT EXISTS admins ( pkid SERIAL PRIMARY KEY, user_pkid INTEGER UNIQUE REFERENCES users(pkid) ON DELETE CASCADE, added_by_pkid INTEGER REFERENCES users(pkid) ON DELETE SET NULL, created_at TIMESTAMPTZ DEFAULT now());
                CREATE TABLE IF NOT EXISTS tags ( pkid SERIAL PRIMARY KEY, name VARCHAR(255) NOT NULL, type VARCHAR(50) NOT NULL, created_at TIMESTAMPTZ DEFAULT now(), UNIQUE(name, type));
                CREATE TABLE IF NOT EXISTS evaluations ( pkid SERIAL PRIMARY KEY, user_pkid INTEGER REFERENCES users(pkid) ON DELETE CASCADE, target_user_pkid INTEGER REFERENCES users(pkid) ON DELETE CASCADE, tag_pkid INTEGER REFERENCES tags(pkid) ON DELETE CASCADE, type VARCHAR(50) NOT NULL, created_at TIMESTAMPTZ DEFAULT now(), UNIQUE(user_pkid, target_user_pkid, tag_pkid));
                CREATE TABLE IF NOT EXISTS favorites ( pkid SERIAL PRIMARY KEY, user_pkid INTEGER REFERENCES users(pkid) ON DELETE CASCADE, target_user_pkid INTEGER REFERENCES users(pkid) ON DELETE CASCADE, created_at TIMESTAMPTZ DEFAULT now(), UNIQUE(user_pkid, target_user_pkid));
                CREATE TABLE IF NOT EXISTS settings ( key VARCHAR(255) PRIMARY KEY, value TEXT, updated_at TIMESTAMPTZ DEFAULT now());
            """)

            # --- 新增的 menu_buttons 表 ---
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS menu_buttons (
                    id SERIAL PRIMARY KEY,
                    command VARCHAR(32) UNIQUE NOT NULL,
                    description VARCHAR(255) NOT NULL,
                    is_enabled BOOLEAN DEFAULT TRUE,
                    sort_order INTEGER DEFAULT 0
                );
            """)
            logger.info("数据表检查和创建完成。")

            # 初始化默认菜单按钮（如果表是空的）
            default_buttons = await connection.fetchval("SELECT 1 FROM menu_buttons LIMIT 1")
            if not default_buttons:
                await connection.executemany("""
                    INSERT INTO menu_buttons (command, description, sort_order) VALUES ($1, $2, $3)
                """, [
                    ('start', '🚀 打开主菜单', 10),
                    ('bang', '🏆 查看排行榜', 20),
                    ('help', 'ℹ️ 获取帮助', 99)
                ])
                logger.info("已初始化默认底部菜单按钮。")
            
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

# 其他函数 (get_pool, db_execute, get_or_create_user 等) 保持不变，此处省略
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

async def get_or_create_user(user: User) -> dict:
    if not user.username: raise ValueError("请先为您的Telegram账户设置一个用户名。")
    username_lower = user.username.lower()
    user_record = await db_fetch_one("SELECT * FROM users WHERE id = $1", user.id)
    if user_record:
        if user_record['username'] != username_lower or user_record['first_name'] != user.first_name:
            await db_execute("UPDATE users SET username = $1, first_name = $2, last_name = $3 WHERE id = $4", username_lower, user.first_name, user.last_name, user.id)
            user_record = await db_fetch_one("SELECT * FROM users WHERE id = $1", user.id)
        return dict(user_record)
    user_record = await db_fetch_one("SELECT * FROM users WHERE username = $1", username_lower)
    if user_record:
        await db_execute("UPDATE users SET id = $1, first_name = $2, last_name = $3 WHERE username = $4", user.id, user.first_name, user.last_name, username_lower)
        user_record = await db_fetch_one("SELECT * FROM users WHERE id = $1", user.id)
        return dict(user_record)
    user_record = await db_fetch_one("INSERT INTO users (id, username, first_name, last_name) VALUES ($1, $2, $3, $4) RETURNING *", user.id, username_lower, user.first_name, user.last_name)
    return dict(user_record)

async def get_or_create_target(username: str) -> dict:
    username_lower = username.lower().strip('@')
    user_record = await db_fetch_one("SELECT * FROM users WHERE username = $1", username_lower)
    if user_record: return dict(user_record)
    await db_execute("INSERT INTO users (username) VALUES ($1) ON CONFLICT (username) DO NOTHING", username_lower)
    user_record = await db_fetch_one("SELECT * FROM users WHERE username = $1", username_lower)
    return dict(user_record)

async def is_admin(user_id: int) -> bool:
    user_pkid = await db_fetch_val("SELECT pkid FROM users WHERE id = $1", user_id)
    if not user_pkid: return False
    return await db_fetch_val("SELECT 1 FROM admins WHERE user_pkid = $1", user_pkid) is not None

async def get_setting(key: str) -> str | None: return await db_fetch_val("SELECT value FROM settings WHERE key = $1", key)
async def set_setting(key: str, value: str | None):
    if value is None: await db_execute("DELETE FROM settings WHERE key = $1", key)
    else: await db_execute("INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()", key, value)
