import logging
import asyncpg
from os import environ

logger = logging.getLogger(__name__)

pool = None

async def init_db():
    """初始化数据库连接池和表结构。"""
    global pool
    if pool:
        return
    
    db_url = environ.get("DATABASE_URL")
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
                    id BIGINT UNIQUE,
                    username VARCHAR(255),
                    first_name VARCHAR(255),
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    pkid SERIAL PRIMARY KEY,
                    name VARCHAR(255) UNIQUE,
                    type VARCHAR(50) NOT NULL, -- 'recommend' or 'block'
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
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key VARCHAR(255) PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            
            # 确保 GOD_USER_ID 存在于 admins 表中
            god_user_id = environ.get("GOD_USER_ID")
            if god_user_id:
                god_user_record = await connection.fetchrow("SELECT pkid FROM users WHERE id = $1", int(god_user_id))
                if god_user_record:
                    await connection.execute("""
                        INSERT INTO admins (user_pkid) VALUES ($1)
                        ON CONFLICT (user_pkid) DO NOTHING;
                    """, god_user_record['pkid'])
                    logger.info(f"已确保 GOD_USER_ID ({god_user_id}) 是管理员。")

            logger.info("所有数据表已检查/创建。")

    except Exception as e:
        logger.critical(f"数据库初始化失败: {e}", exc_info=True)
        raise

async def get_pool():
    if pool is None:
        await init_db()
    return pool

async def db_execute(query, *args):
    """执行一个SQL命令 (INSERT, UPDATE, DELETE)。"""
    db_pool = await get_pool()
    async with db_pool.acquire() as connection:
        return await connection.execute(query, *args)

async def db_fetch_one(query, *args):
    """获取单条记录。"""
    db_pool = await get_pool()
    async with db_pool.acquire() as connection:
        return await connection.fetchrow(query, *args)

async def db_fetch_all(query, *args):
    """获取多条记录。"""
    db_pool = await get_pool()
    async with db_pool.acquire() as connection:
        return await connection.fetch(query, *args)

async def get_or_create_user(user_id: int, username: str = None, first_name: str = None) -> dict:
    """根据Telegram用户ID获取或创建用户，并返回用户记录。"""
    user_record = await db_fetch_one("SELECT * FROM users WHERE id = $1", user_id)
    if user_record:
        # 如果用户名或姓氏有变，更新它
        if (username and user_record['username'] != username) or \
           (first_name and user_record['first_name'] != first_name):
            user_record = await db_fetch_one("""
                UPDATE users SET username = $2, first_name = $3 WHERE id = $1 RETURNING *
            """, user_id, username, first_name)
        return dict(user_record)
    else:
        new_user = await db_fetch_one("""
            INSERT INTO users (id, username, first_name) VALUES ($1, $2, $3) RETURNING *
        """, user_id, username, first_name)
        logger.info(f"创建新用户: {user_id} (@{username})")
        return dict(new_user)

# --- 这就是我们一直缺少的函数 ---
async def get_user_by_username(username: str) -> dict | None:
    """根据用户名从数据库获取用户。"""
    user_record = await db_fetch_one("SELECT * FROM users WHERE username = $1", username)
    return dict(user_record) if user_record else None

async def is_admin(user_id: int) -> bool:
    """检查一个用户是否是管理员。"""
    god_user_id = environ.get("GOD_USER_ID")
    if god_user_id and str(user_id) == god_user_id:
        return True
    
    user_record = await db_fetch_one("SELECT pkid FROM users WHERE id = $1", user_id)
    if not user_record:
        return False
        
    admin_record = await db_fetch_one("SELECT 1 FROM admins WHERE user_pkid = $1", user_record['pkid'])
    return admin_record is not None

async def get_setting(key: str, default: str = None) -> str:
    """从数据库获取设置项。"""
    record = await db_fetch_one("SELECT value FROM settings WHERE key = $1", key)
    return record['value'] if record else default

async def set_setting(key: str, value: str):
    """在数据库中设置或更新一个设置项。"""
    await db_execute("""
        INSERT INTO settings (key, value) VALUES ($1, $2)
        ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW();
    """, key, value)
