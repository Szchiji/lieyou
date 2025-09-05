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
            # --- 核心手术：允许 users.id 为 NULL ---
            # 1. 先删除旧的表（如果存在），以便应用新的结构
            await conn.execute('DROP TABLE IF EXISTS evaluations, favorites, users, tags, settings CASCADE;')
            
            # 2. 重新创建 users 表，id 字段不再是 NOT NULL
            await conn.execute('''
                CREATE TABLE users (
                    pkid SERIAL PRIMARY KEY,
                    id BIGINT UNIQUE,
                    username VARCHAR(255) UNIQUE,
                    first_name VARCHAR(255),
                    is_admin BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPOPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPOPTZ DEFAULT NOW()
                );
            ''')
            # 添加约束，确保 username 或 id 至少有一个存在
            await conn.execute('ALTER TABLE users ADD CONSTRAINT "username_or_id_check" CHECK (username IS NOT NULL OR id IS NOT NULL);')
            
            # 3. 重新创建其他所有表
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
                    created_at TIMESTAMPOPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPOPTZ DEFAULT NOW(),
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
                    created_at TIMESTAMPOPTZ DEFAULT NOW(),
                    UNIQUE (user_pkid, target_user_pkid)
                );
            ''')
            await conn.execute('''
                CREATE TABLE settings (
                    key VARCHAR(255) PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMPOPTZ DEFAULT NOW()
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

# ... db_execute, db_fetch_val 等辅助函数保持不变 ...
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

    # --- 革命性的新逻辑 ---
    if user_id:
        # 如果有ID，这是最可靠的情况
        user = await db_fetch_one("SELECT * FROM users WHERE id = $1", user_id)
        if user:
            # 用户已存在，检查并更新信息
            if (username and user.get('username') != username) or (first_name and user.get('first_name') != first_name):
                return await db_fetch_one("UPDATE users SET username = $1, first_name = $2, updated_at = NOW() WHERE id = $3 RETURNING *", username, first_name, user_id)
            return user
        else:
            # 新用户，但我们有ID。检查是否存在只有用户名的“幽灵档案”
            if username:
                ghost_user = await db_fetch_one("SELECT * FROM users WHERE username = $1 AND id IS NULL", username)
                if ghost_user:
                    # 找到了！为幽灵档案“注入灵魂”（ID），完成转正
                    logger.info(f"用户 {username} (ID: {user_id}) 档案转正成功。")
                    return await db_fetch_one("UPDATE users SET id = $1, first_name = $2, updated_at = NOW() WHERE pkid = $3 RETURNING *", user_id, first_name, ghost_user['pkid'])

            # 如果没有幽灵档案，就创建全新的完整用户
            return await db_fetch_one("INSERT INTO users (id, username, first_name) VALUES ($1, $2, $3) ON CONFLICT (id) DO UPDATE SET username = EXCLUDED.username, first_name = EXCLUDED.first_name, updated_at = NOW() RETURNING *", user_id, username, first_name)
    
    elif username:
        # 如果只提供了用户名，我们就按用户名查找或创建
        # ON CONFLICT (username) 确保了用户名的唯一性
        return await db_fetch_one("INSERT INTO users (username) VALUES ($1) ON CONFLICT (username) DO UPDATE SET updated_at = NOW() RETURNING *", username)

    return None

async def is_admin(user_id: int) -> bool:
    user = await get_or_create_user(user_id=user_id)
    return user and user.get('is_admin', False)

async def get_setting(key: str, default: str = None) -> str:
    value = await db_fetch_val("SELECT value FROM settings WHERE key = $1", key)
    return value if value is not None else default
