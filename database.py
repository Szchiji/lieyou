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
            # --- 核心修正：修复所有 TIMESTAMPOPTZ -> TIMESTAMPTZ 的拼写错误 ---
            await conn.execute('DROP TABLE IF EXISTS evaluations, favorites, users, tags, settings CASCADE;')
            
            await conn.execute('''
                CREATE TABLE users (
                    pkid SERIAL PRIMARY KEY,
                    id BIGINT UNIQUE,
                    username VARCHAR(255) UNIQUE,
                    first_name VARCHAR(255),
                    is_admin BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            ''')
            await conn.execute('ALTER TABLE users ADD CONSTRAINT "username_or_id_check" CHECK (username IS NOT NULL OR id IS NOT NULL);')
            
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS users_username_idx ON users (username);
            ''')
            await conn.execute('''
                CREATE TABLE evaluations (
                    id SERIAL PRIMARY KEY,
                    voter_user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                    target_user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                    tag_id INTEGER NOT NULL,
                    type VARCHAR(10) NOT NULL CHECK (type IN ('recommend', 'block')),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (voter_user_pkid, target_user_pkid)
                );
            ''')
            await conn.execute('''
                CREATE TABLE tags (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    type VARCHAR(10) NOT NULL CHECK (type IN ('recommend', 'block')),
                    UNIQUE (name, type)
                );
            ''')
            await conn.execute('''
                CREATE TABLE favorites (
                    id SERIAL PRIMARY KEY,
                    user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                    target_user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (user_pkid, target_user_pkid)
                );
            ''')
            await conn.execute('''
                CREATE TABLE settings (
                    key VARCHAR(255) PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            ''')
        logger.info("数据库已按新结构彻底重建。")
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
    if username:
        username = username.lstrip('@')

    if user_id:
        user = await db_fetch_one("SELECT * FROM users WHERE id = $1", user_id)
        if user:
            if (username and user.get('username') != username) or (first_name and user.get('first_name') != first_name):
                return await db_fetch_one("UPDATE users SET username = $1, first_name = $2, updated_at = NOW() WHERE id = $3 RETURNING *", username, first_name, user_id)
            return user
        else:
            if username:
                ghost_user = await db_fetch_one("SELECT * FROM users WHERE username = $1 AND id IS NULL", username)
                if ghost_user:
                    logger.info(f"用户 {username} (ID: {user_id}) 档案转正成功。")
                    return await db_fetch_one("UPDATE users SET id = $1, first_name = $2, updated_at = NOW() WHERE pkid = $3 RETURNING *", user_id, first_name, ghost_user['pkid'])

            return await db_fetch_one("INSERT INTO users (id, username, first_name) VALUES ($1, $2, $3) ON CONFLICT (id) DO UPDATE SET username = EXCLUDED.username, first_name = EXCLUDED.first_name, updated_at = NOW() RETURNING *", user_id, username, first_name)
    
    elif username:
        return await db_fetch_one("INSERT INTO users (username) VALUES ($1) ON CONFLICT (username) DO UPDATE SET updated_at = NOW() RETURNING *", username)

    return None

async def is_admin(user_id: int) -> bool:
    user = await get_or_create_user(user_id=user_id)
    return user and user.get('is_admin', False)

async def get_setting(key: str, default: str = None) -> str:
    value = await db_fetch_val("SELECT value FROM settings WHERE key = $1", key)
    return value if value is not None else default
