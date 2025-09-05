import logging
import os
import asyncpg
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)
pool = None

async def init_db():
    global pool
    if pool:
        return
    try:
        pool = await asyncpg.create_pool(
            dsn=os.environ.get("DATABASE_URL"),
            min_size=1,
            max_size=10
        )
        logger.info("数据库连接池已成功创建。")
        async with pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    pkid SERIAL PRIMARY KEY,
                    id BIGINT UNIQUE NOT NULL,
                    username VARCHAR(255) UNIQUE,
                    first_name VARCHAR(255),
                    is_admin BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPOPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPOPTZ DEFAULT NOW()
                );
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS users_username_idx ON users (username);
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS evaluations (
                    id SERIAL PRIMARY KEY,
                    voter_user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                    target_user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                    tag_id INTEGER NOT NULL,
                    type VARCHAR(10) NOT NULL CHECK (type IN ('recommend', 'block')),
                    created_at TIMESTAMPOPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPOPTZ DEFAULT NOW(),
                    UNIQUE (voter_user_pkid, target_user_pkid)
                );
            ''')
            # ... (其他表的创建语句保持不变)
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tags (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    type VARCHAR(10) NOT NULL CHECK (type IN ('recommend', 'block')),
                    UNIQUE (name, type)
                );
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS favorites (
                    id SERIAL PRIMARY KEY,
                    user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                    target_user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                    created_at TIMESTAMPOPTZ DEFAULT NOW(),
                    UNIQUE (user_pkid, target_user_pkid)
                );
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key VARCHAR(255) PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMPOPTZ DEFAULT NOW()
                );
            ''')
        logger.info("数据库初始化/验证完成。")
    except Exception as e:
        logger.critical(f"数据库初始化失败: {e}", exc_info=True)
        raise

async def get_pool():
    if pool is None:
        await init_db()
    return pool

async def db_execute(query, *args):
    db_pool = await get_pool()
    async with db_pool.acquire() as conn:
        return await conn.execute(query, *args)

async def db_fetch_val(query, *args):
    db_pool = await get_pool()
    async with db_pool.acquire() as conn:
        return await conn.fetchval(query, *args)

async def db_fetch_one(query, *args) -> Optional[Dict[str, Any]]:
    db_pool = await get_pool()
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(query, *args)
        return dict(row) if row else None

async def db_fetch_all(query, *args) -> list[Dict[str, Any]]:
    db_pool = await get_pool()
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(query, *args)
        return [dict(row) for row in rows]

async def get_or_create_user(user_id: int = None, username: str = None, first_name: str = None) -> Optional[Dict[str, Any]]:
    if not user_id and not username:
        return None

    # --- 核心修正：重写整个函数的逻辑 ---
    if user_id:
        # 优先使用ID查询，这是最可靠的方式
        user = await db_fetch_one("SELECT * FROM users WHERE id = $1", user_id)
        if user:
            # 如果找到了，顺便更新一下可能变化的 username 和 first_name
            if (username and user.get('username') != username) or \
               (first_name and user.get('first_name') != first_name):
                user = await db_fetch_one(
                    "UPDATE users SET username = $1, first_name = $2, updated_at = NOW() WHERE id = $3 RETURNING *",
                    username, first_name, user_id
                )
            return user
        else:
            # 如果用ID找不到，说明是新用户，创建之
            return await db_fetch_one(
                """INSERT INTO users (id, username, first_name) VALUES ($1, $2, $3)
                   ON CONFLICT (id) DO UPDATE SET username = EXCLUDED.username, first_name = EXCLUDED.first_name, updated_at = NOW()
                   RETURNING *""",
                user_id, username, first_name
            )
    elif username:
        # 如果只提供了用户名，我们只查询，不创建
        # 因为没有 user_id，我们无法创建有效的用户记录
        username = username.lstrip('@')
        return await db_fetch_one("SELECT * FROM users WHERE username = $1", username)

    return None # 兜底

async def is_admin(user_id: int) -> bool:
    user = await get_or_create_user(user_id=user_id)
    return user and user.get('is_admin', False)

async def get_setting(key: str, default: str = None) -> str:
    value = await db_fetch_val("SELECT value FROM settings WHERE key = $1", key)
    return value if value is not None else default
