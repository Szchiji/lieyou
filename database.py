import logging
import asyncpg
import os
from datetime import datetime
from telegram import User as TelegramUser

logger = logging.getLogger(__name__)

pool = None

async def init_db():
    """初始化数据库连接池和表结构。"""
    global pool
    if pool:
        return
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.critical("DATABASE_URL 环境变量未设置！")
        raise ValueError("DATABASE_URL is not set")
    try:
        pool = await asyncpg.create_pool(dsn=db_url, min_size=1, max_size=10)
        logger.info("数据库连接池已成功创建。")
        async with pool.acquire() as connection:
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    pkid SERIAL PRIMARY KEY,
                    username VARCHAR(255) UNIQUE NOT NULL,
                    id BIGINT UNIQUE,
                    first_name VARCHAR(255),
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    pkid SERIAL PRIMARY KEY,
                    name VARCHAR(255) UNIQUE,
                    type VARCHAR(50) NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS evaluations (
                    pkid SERIAL PRIMARY KEY,
                    user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                    target_user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                    tag_pkid INTEGER NOT NULL REFERENCES tags(pkid) ON DELETE CASCADE,
                    type VARCHAR(50) NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(user_pkid, target_user_pkid, tag_pkid)
                );
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    pkid SERIAL PRIMARY KEY,
                    user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                    target_user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(user_pkid, target_user_pkid)
                );
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    pkid SERIAL PRIMARY KEY,
                    user_pkid INTEGER NOT NULL UNIQUE REFERENCES users(pkid) ON DELETE CASCADE,
                    added_by_pkid INTEGER REFERENCES users(pkid),
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            # --- settings 表是“入群设置”功能的基础 ---
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key VARCHAR(255) PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            
            god_user_id = os.environ.get("GOD_USER_ID")
            if god_user_id:
                try:
                    user_id = int(god_user_id)
                    # 确保God User存在于users表中
                    await connection.execute("""
                        INSERT INTO users (id, username, first_name) VALUES ($1, $2, $3)
                        ON CONFLICT (id) DO UPDATE SET username = COALESCE(EXCLUDED.username, users.username), first_name = COALESCE(EXCLUDED.first_name, users.first_name)
                    """, user_id, f"god_user_{user_id}", "God User")
                    
                    # 获取God User的pkid并设为管理员
                    god_user_record = await connection.fetchrow("SELECT pkid FROM users WHERE id = $1", user_id)
                    if god_user_record:
                        await connection.execute(
                            "INSERT INTO admins (user_pkid) VALUES ($1) ON CONFLICT (user_pkid) DO NOTHING;",
                            god_user_record['pkid']
                        )
                        logger.info(f"已确保 GOD_USER_ID ({god_user_id}) 是管理员。")
                except (ValueError, asyncpg.PostgresError) as e:
                     logger.error(f"GOD_USER_ID 设置或插入数据库时出错: {e}")
            logger.info("所有数据表已检查/创建。")
    except Exception as e:
        logger.critical(f"数据库初始化失败: {e}", exc_info=True)
        raise

async def get_pool():
    if pool is None:
        await init_db()
    return pool

async def db_execute(query, *args):
    db_pool = await get_pool()
    async with db_pool.acquire() as c:
        return await c.execute(query, *args)

async def db_fetch_one(query, *args):
    db_pool = await get_pool()
    async with db_pool.acquire() as c:
        return await c.fetchrow(query, *args)

async def db_fetch_all(query, *args):
    db_pool = await get_pool()
    async with db_pool.acquire() as c:
        return await c.fetch(query, *args)

async def db_fetch_val(query, *args):
    """获取查询结果的单个值。"""
    db_pool = await get_pool()
    async with db_pool.acquire() as c:
        return await c.fetchval(query, *args)

async def get_or_create_user(tg_user: TelegramUser) -> dict:
    if not tg_user or not tg_user.id:
        raise ValueError("需要一个有效的Telegram用户对象。")
    if not tg_user.username:
        raise ValueError("操作发起者必须设置一个Telegram用户名。")
    
    username_lower = tg_user.username.lower()
    user_record = await db_fetch_one("SELECT * FROM users WHERE id = $1", tg_user.id)
    
    if user_record:
        if user_record['username'] != username_lower or user_record['first_name'] != tg_user.first_name:
            user_record = await db_fetch_one(
                "UPDATE users SET username = $1, first_name = $2 WHERE id = $3 RETURNING *",
                username_lower, tg_user.first_name, tg_user.id
            )
        return dict(user_record)
    else:
        new_user = await db_fetch_one(
            "INSERT INTO users (id, username, first_name) VALUES ($1, $2, $3) "
            "ON CONFLICT (username) DO UPDATE SET id = EXCLUDED.id, first_name = EXCLUDED.first_name RETURNING *",
            tg_user.id, username_lower, tg_user.first_name
        )
        logger.info(f"创建新用户: {tg_user.id} (@{tg_user.username})")
        return dict(new_user)

async def get_or_create_target(username: str) -> dict:
    if not username:
        raise ValueError("用户名不能为空")
    username_lower = username.lower()
    user_record = await db_fetch_one("SELECT * FROM users WHERE username = $1", username_lower)
    if user_record:
        return dict(user_record)
    
    new_user = await db_fetch_one(
        "INSERT INTO users (username) VALUES ($1) ON CONFLICT (username) DO NOTHING RETURNING *",
        username_lower
    )
    if not new_user: # 如果因为并发冲突没返回，就再查一次
        new_user = await db_fetch_one("SELECT * FROM users WHERE username = $1", username_lower)

    logger.info(f"为目标字符串 @{username_lower} 创建了新的数据库条目。")
    return dict(new_user)

async def get_user_by_id(user_id: int) -> dict | None:
    user_record = await db_fetch_one("SELECT * FROM users WHERE id = $1", user_id)
    return dict(user_record) if user_record else None

async def is_admin(user_id: int) -> bool:
    god_user_id = os.environ.get("GOD_USER_ID")
    if god_user_id and str(user_id) == god_user_id:
        return True
    user_record = await get_user_by_id(user_id)
    if not user_record:
        return False
    admin_record = await db_fetch_one("SELECT 1 FROM admins WHERE user_pkid = $1", user_record['pkid'])
    return admin_record is not None

# --- get_setting 和 set_setting 是“入群设置”功能所必需的函数 ---
async def get_setting(key: str, default: str = None) -> str:
    """从settings表中获取一个值。"""
    record = await db_fetch_one("SELECT value FROM settings WHERE key = $1", key)
    # 如果记录存在但值为None或空字符串，也视为未设置，返回默认值
    if record and record['value']:
        return record['value']
    return default

async def set_setting(key: str, value: str):
    """在settings表中设置一个键值对。"""
    await db_execute(
        "INSERT INTO settings (key, value, updated_at) VALUES ($1, $2, NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW();",
        key, value
    )
