import asyncpg
import logging
from os import environ

# 日志配置
logger = logging.getLogger(__name__)

# 全局数据库连接池
pool = None

async def init_pool():
    """初始化数据库连接池"""
    global pool
    if pool:
        return
    try:
        pool = await asyncpg.create_pool(
            dsn=environ.get("DATABASE_URL"),
            min_size=1,
            max_size=10
        )
        logger.info("✅ 数据库连接池已成功创建。")
    except Exception as e:
        logger.critical(f"❌ 无法创建数据库连接池: {e}", exc_info=True)
        raise

async def close_pool():
    """关闭数据库连接池"""
    global pool
    if pool:
        await pool.close()
        pool = None
        logger.info("🔌 数据库连接池已关闭。")

async def db_execute(query, *args):
    """执行SQL命令 (INSERT, UPDATE, DELETE)"""
    async with pool.acquire() as conn:
        await conn.execute(query, *args)

async def db_fetch_one(query, *args):
    """获取单条记录"""
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)

async def db_fetch_all(query, *args):
    """获取多条记录"""
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)

async def create_tables():
    """创建所有必要的数据库表（如果不存在）"""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                is_admin BOOLEAN DEFAULT FALSE,
                is_bot BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS tags (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                type TEXT NOT NULL, -- 'recommend' 或 'block'
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS votes (
                id SERIAL PRIMARY KEY,
                voter_user_id BIGINT REFERENCES users(id),
                target_user_id BIGINT REFERENCES users(id),
                tag_id INTEGER REFERENCES tags(id),
                comment TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(voter_user_id, target_user_id, tag_id)
            );
            CREATE TABLE IF NOT EXISTS favorites (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(id),
                target_user_id BIGINT REFERENCES users(id),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(user_id, target_user_id)
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        # 插入默认设置项，如果它们不存在的话
        await conn.execute("""
            INSERT INTO settings (key, value) VALUES
            ('start_message', NULL),
            ('auto_delete_timeout', '300') -- 默认300秒（5分钟）
            ON CONFLICT (key) DO NOTHING;
        """)
        logger.info("✅ 数据库表结构已验证/创建。")

async def is_admin(user_id: int) -> bool:
    """检查用户是否是管理员"""
    user = await db_fetch_one("SELECT is_admin FROM users WHERE id = $1", user_id)
    return user and user['is_admin']

async def get_setting(key: str, default: str = None) -> str:
    """从数据库获取设置项"""
    setting = await db_fetch_one("SELECT value FROM settings WHERE key = $1", key)
    return setting['value'] if setting and setting['value'] is not None else default

async def set_setting(key: str, value: str):
    """更新或插入设置项"""
    await db_execute(
        "INSERT INTO settings (key, value, updated_at) VALUES ($1, $2, NOW()) ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()",
        key, value
    )
