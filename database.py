import asyncpg
import logging
from os import environ
from telegram import User

logger = logging.getLogger(__name__)
pool = None

async def get_pool():
    global pool
    if pool is None:
        try:
            pool = await asyncpg.create_pool(
                dsn=environ.get("DATABASE_URL"),
                min_size=1,
                max_size=10,
                command_timeout=60,
            )
            logger.info("数据库连接池已成功创建。")
        except Exception as e:
            logger.critical(f"无法创建数据库连接池: {e}", exc_info=True)
            raise
    return pool

async def init_db():
    conn = await(await get_pool()).acquire()
    try:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                pkid SERIAL PRIMARY KEY,
                id BIGINT UNIQUE,
                username TEXT,
                first_name TEXT
            );
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS tags (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                description TEXT
            );
        ''')
        # 核心改动：用新的 evaluations 表替换旧的 votes 表
        await conn.execute('DROP TABLE IF EXISTS votes;') # 删除旧表
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS evaluations (
                id SERIAL PRIMARY KEY,
                voter_user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                target_user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE RESTRICT,
                type TEXT NOT NULL, -- 'recommend' or 'block'
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (voter_user_pkid, target_user_pkid)
            );
        ''')
        await conn.execute('''
            CREATE OR REPLACE FUNCTION update_updated_at_column()
            RETURNS TRIGGER AS $$
            BEGIN
               NEW.updated_at = NOW();
               RETURN NEW;
            END;
            $$ language 'plpgsql';
        ''')
        await conn.execute('''
            DROP TRIGGER IF EXISTS update_evaluations_updated_at ON evaluations;
            CREATE TRIGGER update_evaluations_updated_at
            BEFORE UPDATE ON evaluations
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS favorites (
                id SERIAL PRIMARY KEY,
                user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                target_user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                UNIQUE (user_pkid, target_user_pkid)
            );
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                id SERIAL PRIMARY KEY,
                user_pkid INTEGER NOT NULL UNIQUE REFERENCES users(pkid) ON DELETE CASCADE
            );
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        ''')
        logger.info("数据库初始化/验证完成。")
    finally:
        await conn.close()

async def db_execute(query, *args):
    conn = await(await get_pool()).acquire()
    try:
        return await conn.execute(query, *args)
    finally:
        await conn.close()

async def db_fetch_val(query, *args):
    conn = await(await get_pool()).acquire()
    try:
        return await conn.fetchval(query, *args)
    finally:
        await conn.close()

async def db_fetch_one(query, *args):
    conn = await(await get_pool()).acquire()
    try:
        return await conn.fetchrow(query, *args)
    finally:
        await conn.close()

async def db_fetch_all(query, *args):
    conn = await(await get_pool()).acquire()
    try:
        return await conn.fetch(query, *args)
    finally:
        await conn.close()

async def get_or_create_user(user_id: int = None, username: str = None, first_name: str = None) -> dict:
    if not user_id and not username: return None
    
    # 优先使用 ID 查询
    if user_id:
        user = await db_fetch_one("SELECT * FROM users WHERE id = $1", user_id)
        if user:
            # 如果用户信息有变动，则更新
            if (username and user['username'] != username) or (first_name and user['first_name'] != first_name):
                await db_execute("UPDATE users SET username = $1, first_name = $2 WHERE id = $3", username, first_name, user_id)
                return await db_fetch_one("SELECT * FROM users WHERE id = $1", user_id)
            return user

    # 如果没有 ID 或通过 ID 找不到，再尝试用 username 查询
    if username:
        user = await db_fetch_one("SELECT * FROM users WHERE username = $1", username)
        if user:
             # 如果用户信息有变动，则更新
            if (user_id and user['id'] != user_id) or (first_name and user['first_name'] != first_name):
                 await db_execute("UPDATE users SET id = $1, first_name = $2 WHERE username = $3", user_id, first_name, username)
                 return await db_fetch_one("SELECT * FROM users WHERE username = $1", username)
            return user
    
    # 如果都找不到，则创建新用户
    if user_id or username:
        sql = "INSERT INTO users (id, username, first_name) VALUES ($1, $2, $3) ON CONFLICT (id) DO UPDATE SET username = $2, first_name = $3 RETURNING *"
        # 如果没有 user_id，则在 username 上做冲突处理
        if not user_id and username:
            sql = "INSERT INTO users (username, first_name) VALUES ($1, $2) ON CONFLICT (username) DO UPDATE SET first_name = $2 RETURNING *"
            return await db_fetch_one(sql, username, first_name)
        
        return await db_fetch_one(sql, user_id, username, first_name)
    
    return None

async def is_admin(user_id: int) -> bool:
    user = await get_or_create_user(user_id)
    if not user: return False
    return await db_fetch_val("SELECT 1 FROM admins WHERE user_pkid = $1", user['pkid']) is not None

async def get_setting(key: str, default: str = None) -> str:
    value = await db_fetch_val("SELECT value FROM settings WHERE key = $1", key)
    return value if value is not None else default
