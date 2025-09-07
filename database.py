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
    包含健康检查和强制重建逻辑。
    """
    global pool
    
    # --- 新增的健康检查与强制刷新逻辑 ---
    if pool is not None and not pool.is_closing():
        try:
            # 尝试执行一个最简单的查询来检查连接是否健康
            async with pool.acquire() as connection:
                await connection.fetchval("SELECT 1")
            logger.info("数据库连接池已存在且健康，跳过初始化。")
            return
        except Exception as e:
            logger.warning(f"检测到数据库连接池不健康: {e}。将强制关闭并重建。")
            await pool.close()
            pool = None # 强制设为None，以便重新创建

    if pool is not None and pool.is_closing():
         logger.info("数据库连接池正在关闭中，等待重建。")
         pool = None

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.critical("DATABASE_URL 环境变量未设置！")
        raise ValueError("DATABASE_URL is not set")

    try:
        logger.info("正在创建新的数据库连接池...")
        pool = await asyncpg.create_pool(database_url)
        logger.info("数据库连接池已成功创建。")
        
        async with pool.acquire() as connection:
            logger.info("正在检查并创建数据表...")
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
            # 创建 admins 表
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    pkid SERIAL PRIMARY KEY,
                    user_pkid INTEGER UNIQUE REFERENCES users(pkid) ON DELETE CASCADE,
                    added_by_pkid INTEGER REFERENCES users(pkid) ON DELETE SET NULL,
                    created_at TIMESTAMPTZ DEFAULT now()
                );
            """)
            # 创建 tags 表
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    pkid SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    type VARCHAR(50) NOT NULL, -- 'recommend' or 'block'
                    created_at TIMESTAMPTZ DEFAULT now(),
                    UNIQUE(name, type)
                );
            """)
            # 创建 evaluations 表
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
            # 创建 favorites 表
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    pkid SERIAL PRIMARY KEY,
                    user_pkid INTEGER REFERENCES users(pkid) ON DELETE CASCADE,
                    target_user_pkid INTEGER REFERENCES users(pkid) ON DELETE CASCADE,
                    created_at TIMESTAMPTZ DEFAULT now(),
                    UNIQUE(user_pkid, target_user_pkid)
                );
            """)
            # 创建 settings 表
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key VARCHAR(255) PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMPTZ DEFAULT now()
                );
            """)
            logger.info("数据表检查和创建完成。")
            
            # 检查并设置 GOD_USER_ID
            god_user_id_str = os.environ.get("GOD_USER_ID")
            if god_user_id_str:
                try:
                    god_user_id = int(god_user_id_str)
                    god_user_record = await connection.fetchrow("SELECT pkid FROM users WHERE id = $1", god_user_id)
                    if god_user_record:
                        await connection.execute(
                            "INSERT INTO admins (user_pkid) VALUES ($1) ON CONFLICT (user_pkid) DO NOTHING",
                            god_user_record['pkid']
                        )
                        logger.info(f"已确保 GOD 用户 (ID: {god_user_id}) 是管理员。")
                    else:
                        logger.warning(f"GOD_USER_ID (ID: {god_user_id}) 在 users 表中未找到。请确保该用户已与机器人互动过。")
                except ValueError:
                    logger.error("GOD_USER_ID 环境变量不是一个有效的整数。")
                except Exception as e:
                    logger.error(f"设置 GOD 用户时出错: {e}")

    except Exception as e:
        logger.critical(f"数据库初始化失败: {e}", exc_info=True)
        raise

async def get_pool():
    """获取数据库连接池。如果未初始化，则先进行初始化。"""
    global pool
    if pool is None:
        await init_db()
    return pool

async def db_execute(query, *args):
    """执行一个数据库写操作 (INSERT, UPDATE, DELETE)。"""
    conn_pool = await get_pool()
    async with conn_pool.acquire() as connection:
        return await connection.execute(query, *args)

async def db_fetch_all(query, *args):
    """执行一个数据库读操作，并返回所有结果。"""
    conn_pool = await get_pool()
    async with conn_pool.acquire() as connection:
        return await connection.fetch(query, *args)

async def db_fetch_one(query, *args):
    """执行一个数据库读操作，并返回第一条结果。"""
    conn_pool = await get_pool()
    async with conn_pool.acquire() as connection:
        return await connection.fetchrow(query, *args)

async def db_fetch_val(query, *args):
    """执行一个数据库读操作，并返回第一条结果的第一个值。"""
    conn_pool = await get_pool()
    async with conn_pool.acquire() as connection:
        return await connection.fetchval(query, *args)

async def get_or_create_user(user: User) -> dict:
    """
    根据 Telegram User 对象获取或创建用户记录。
    如果用户没有设置 username，会引发 ValueError。
    """
    if not user.username:
        raise ValueError("用户必须设置用户名才能使用此机器人。")
        
    username_lower = user.username.lower()
    
    user_record = await db_fetch_one(
        "SELECT * FROM users WHERE id = $1", user.id
    )
    if user_record:
        # 如果用户名或姓名有变化，则更新
        if user_record['username'] != username_lower or user_record['first_name'] != user.first_name or user_record['last_name'] != user.last_name:
            user_record = await db_fetch_one(
                "UPDATE users SET username = $1, first_name = $2, last_name = $3 WHERE id = $4 RETURNING *",
                username_lower, user.first_name, user.last_name, user.id
            )
    else:
        try:
            user_record = await db_fetch_one(
                "INSERT INTO users (id, username, first_name, last_name) VALUES ($1, $2, $3, $4) RETURNING *",
                user.id, username_lower, user.first_name, user.last_name
            )
        except asyncpg.UniqueViolationError:
            # 极小概率下，用户在两次查询之间更改了用户名，导致唯一性冲突
            user_record = await db_fetch_one("SELECT * FROM users WHERE username = $1", username_lower)
            if user_record:
                 user_record = await db_fetch_one("SELECT * FROM users WHERE id = $1", user.id)
            else:
                # 如果还是找不到，就重新抛出异常
                raise
    return dict(user_record)

async def get_or_create_target(username: str) -> dict:
    """
    根据 username 获取用户记录。如果用户不存在，则创建一个"虚拟"记录。
    这个虚拟记录没有 first_name, last_name, 和 id。
    """
    username_lower = username.lower()
    user_record = await db_fetch_one("SELECT * FROM users WHERE username = $1", username_lower)
    if not user_record:
        # 创建一个只有username的虚拟记录
        user_record = await db_fetch_one(
            "INSERT INTO users (username) VALUES ($1) ON CONFLICT (username) DO UPDATE SET username=EXCLUDED.username RETURNING *",
            username_lower
        )
    return dict(user_record)


async def is_admin(user_id: int) -> bool:
    """检查一个用户是否是管理员。"""
    user_pkid = await db_fetch_val("SELECT pkid FROM users WHERE id = $1", user_id)
    if not user_pkid:
        return False
    admin_record = await db_fetch_one("SELECT 1 FROM admins WHERE user_pkid = $1", user_pkid)
    return admin_record is not None

async def get_setting(key: str) -> str | None:
    """从 settings 表获取一个设置项的值。"""
    return await db_fetch_val("SELECT value FROM settings WHERE key = $1", key)

async def set_setting(key: str, value: str | None):
    """在 settings 表中设置一个键值对。"""
    if value is None:
        await db_execute("DELETE FROM settings WHERE key = $1", key)
    else:
        await db_execute(
            """
            INSERT INTO settings (key, value) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
            """,
            key, value
        )
