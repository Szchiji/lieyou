import asyncpg
import logging
from os import environ
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# 全局数据库连接池
pool = None

async def get_pool():
    """获取或创建数据库连接池"""
    global pool
    if pool is None:
        try:
            pool = await asyncpg.create_pool(
                dsn=environ.get("DATABASE_URL"),
                min_size=1,
                max_size=10
            )
            logger.info("数据库连接池创建成功。")
        except Exception as e:
            logger.critical(f"无法连接到数据库: {e}")
            pool = None
    return pool

async def run_migration(conn):
    """
    非破坏性地更新数据库表结构。
    """
    # 检查 users 表是否存在 last_active_at 列
    has_last_active_at = await conn.fetchval("""
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'users' AND column_name = 'last_active_at'
        );
    """)
    if not has_last_active_at:
        logger.info("检测到旧版 'users' 表，正在添加 'last_active_at' 列...")
        await conn.execute("ALTER TABLE users ADD COLUMN last_active_at TIMESTAMPTZ DEFAULT (now() AT TIME ZONE 'utc');")
        logger.info("'last_active_at' 列添加成功。")

async def init_db():
    """初始化数据库，创建所有需要的表并运行迁移"""
    pool = await get_pool()
    if not pool:
        logger.error("数据库连接池不可用，无法初始化数据库。")
        return
        
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id BIGINT PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        is_admin BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMPTZ DEFAULT (now() AT TIME ZONE 'utc')
                    );
                """)

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS tags (
                        id SERIAL PRIMARY KEY,
                        name TEXT UNIQUE NOT NULL,
                        type TEXT NOT NULL CHECK (type IN ('recommend', 'block')),
                        created_at TIMESTAMPTZ DEFAULT (now() AT TIME ZONE 'utc')
                    );
                """)

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS votes (
                        id SERIAL PRIMARY KEY,
                        voter_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        target_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                        message_id BIGINT,
                        chat_id BIGINT,
                        created_at TIMESTAMPTZ DEFAULT (now() AT TIME ZONE 'utc'),
                        UNIQUE (voter_user_id, target_user_id, tag_id)
                    );
                """)
                
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS favorites (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        target_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        UNIQUE (user_id, target_user_id)
                    );
                """)

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TIMESTAMPTZ DEFAULT (now() AT TIME ZONE 'utc')
                    );
                """)
                logger.info("数据库表结构检查/创建完成。")

                # 运行数据库迁移脚本
                await run_migration(conn)

                # 确保创建者是管理员
                creator_id_str = environ.get("CREATOR_ID")
                if creator_id_str:
                    try:
                        creator_id = int(creator_id_str)
                        await conn.execute(
                            "INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE",
                            creator_id
                        )
                        logger.info(f"已确保创建者 (ID: {creator_id}) 的管理员权限。")
                    except ValueError:
                        logger.error("CREATOR_ID 格式错误，无法设置初始管理员。")
                
                logger.info("数据库初始化流程完成。")

            except Exception as e:
                logger.error(f"数据库初始化/迁移过程中发生错误: {e}", exc_info=True)
                raise # 抛出异常以回滚事务

async def db_execute(query, *args):
    pool = await get_pool();
    if not pool: return
    async with pool.acquire() as conn: await conn.execute(query, *args)

async def db_fetch_one(query, *args):
    pool = await get_pool();
    if not pool: return None
    async with pool.acquire() as conn: return await conn.fetchrow(query, *args)

async def db_fetch_all(query, *args):
    pool = await get_pool();
    if not pool: return []
    async with pool.acquire() as conn: return await conn.fetch(query, *args)

async def db_fetchval(query, *args):
    pool = await get_pool();
    if not pool: return None
    async with pool.acquire() as conn: return await conn.fetchval(query, *args)

@asynccontextmanager
async def db_transaction():
    pool = await get_pool()
    if not pool: raise ConnectionError("数据库连接池不可用")
    async with pool.acquire() as conn:
        async with conn.transaction(): yield conn

async def update_user_activity(user_id: int, username: str, first_name: str):
    await db_execute(
        """
        INSERT INTO users (id, username, first_name, last_active_at)
        VALUES ($1, $2, $3, now() AT TIME ZONE 'utc')
        ON CONFLICT (id) DO UPDATE SET
            username = $2,
            first_name = $3,
            last_active_at = now() AT TIME ZONE 'utc';
        """,
        user_id, username, first_name
    )

async def is_admin(user_id: int) -> bool:
    creator_id_str = environ.get("CREATOR_ID")
    if creator_id_str and user_id == int(creator_id_str): return True
    user = await db_fetch_one("SELECT is_admin FROM users WHERE id = $1", user_id)
    return user['is_admin'] if user else False

async def get_setting(key: str, default: str = None) -> str:
    value = await db_fetchval("SELECT value FROM settings WHERE key = $1", key)
    return value if value is not None else default

async def set_setting(key: str, value: str):
    await db_execute(
        """
        INSERT INTO settings (key, value, updated_at) VALUES ($1, $2, now() AT TIME ZONE 'utc')
        ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = now() AT TIME ZONE 'utc';
        """,
        key, value
    )
