import logging
import asyncpg
from os import environ
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

# 配置日志
logger = logging.getLogger(__name__)

# 数据库连接池
db_pool = None

async def init_pool():
    """初始化数据库连接池"""
    global db_pool
    database_url = environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL 环境变量未设置")
    
    try:
        db_pool = await asyncpg.create_pool(database_url, min_size=1, max_size=10)
        logger.info("✅ 数据库连接池初始化成功")
    except Exception as e:
        logger.error(f"❌ 数据库连接池初始化失败: {e}", exc_info=True)
        raise

async def close_pool():
    """关闭数据库连接池"""
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("🔌 数据库连接池已关闭")

@asynccontextmanager
async def db_transaction():
    """数据库事务上下文管理器"""
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            yield conn

async def db_execute(query: str, *args) -> str:
    """执行数据库写操作"""
    async with db_pool.acquire() as conn:
        return await conn.execute(query, *args)

async def db_fetch_all(query: str, *args) -> List[Dict]:
    """获取多行数据"""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(query, *args)
        return [dict(row) for row in rows]

async def db_fetch_one(query: str, *args) -> Optional[Dict]:
    """获取单行数据"""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(query, *args)
        return dict(row) if row else None

async def db_fetchval(query: str, *args):
    """获取单个值"""
    async with db_pool.acquire() as conn:
        return await conn.fetchval(query, *args)

async def update_user_activity(user_id: int, username: str = None, first_name: str = None):
    """更新用户活动时间并确保用户存在"""
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (id, username, first_name, last_activity) 
                VALUES ($1, $2, $3, NOW()) 
                ON CONFLICT (id) DO UPDATE SET 
                    username = COALESCE($2, users.username),
                    first_name = COALESCE($3, users.first_name),
                    last_activity = NOW()
            """, user_id, username, first_name)
    except Exception as e:
        logger.error(f"更新用户活动时出错: {e}", exc_info=True)

async def create_tables():
    """创建并迁移数据库表"""
    async with db_pool.acquire() as conn:
        logger.info("步骤 1: 确保所有表都存在...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                is_admin BOOLEAN DEFAULT FALSE,
                last_activity TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL CHECK (type IN ('recommend', 'block')),
                created_by BIGINT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)
        
        # FINAL FIX: Changed tag_ids to tag_id to match all other files.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reputations (
                id SERIAL PRIMARY KEY,
                target_id BIGINT NOT NULL,
                voter_id BIGINT NOT NULL,
                is_positive BOOLEAN NOT NULL,
                tag_id INTEGER[],
                comment TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                UNIQUE(target_id, voter_id)
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                target_id BIGINT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                UNIQUE(user_id, target_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_by BIGINT,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS erasure_records (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                type TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)

        logger.info("步骤 2: 正在检查并执行列迁移...")
        # Add a new column with the correct name if the old one exists
        if await db_fetchval("SELECT 1 FROM information_schema.columns WHERE table_name='reputations' AND column_name='tag_ids'"):
            logger.info("发现旧的 'tag_ids' 列，准备迁移到 'tag_id'...")
            # Add the new column if it doesn't exist
            await conn.execute("ALTER TABLE reputations ADD COLUMN IF NOT EXISTS tag_id INTEGER[]")
            # Copy data from old to new
            await conn.execute("UPDATE reputations SET tag_id = tag_ids WHERE tag_id IS NULL")
            # Drop the old column
            await conn.execute("ALTER TABLE reputations DROP COLUMN tag_ids")
            logger.info("✅ 已成功将 'tag_ids' 迁移到 'tag_id'")

        logger.info("步骤 3: 插入默认设置...")
        await conn.execute("""
            INSERT INTO settings (key, value) VALUES 
            ('admin_password', 'oracleadmin'),
            ('min_votes_for_leaderboard', '3'),
            ('leaderboard_size', '10'),
            ('start_message', '我是 **神谕者 (The Oracle)**，洞察世间一切信誉的实体。

**聆听神谕:**
1. 在群聊中直接 `@某人` 或发送 `查询 @某人`，即可向我求问关于此人的神谕之卷。
2. 使用下方按钮，可窥探时代群像或管理你的星盘。')
            ON CONFLICT (key) DO NOTHING
        """)
        
        logger.info("✅ 数据库表初始化/迁移完成")

# === 业务逻辑函数 ===

async def get_or_create_user_by_username(username: str) -> Optional[Dict]:
    """通过用户名获取用户，如果不存在则创建虚拟用户记录"""
    try:
        target_user = await get_user_by_username(username)
        if target_user:
            return target_user

        logger.info(f"用户 @{username} 不存在，将为其创建虚拟档案...")
        virtual_user_id = abs(hash(username))
        
        await db_execute(
            "INSERT INTO users (id, username, first_name) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
            virtual_user_id, username, f"@{username}"
        )
        
        return {'id': virtual_user_id, 'username': username, 'first_name': f"@{username}"}
    except Exception as e:
        logger.error(f"获取或创建用户 @{username} 时失败: {e}", exc_info=True)
        return None


async def get_all_tags_by_type(tag_type: str) -> List[Dict]:
    """根据类型获取所有标签"""
    return await db_fetch_all("SELECT id, name FROM tags WHERE type = $1 ORDER BY name", tag_type)

async def is_admin(user_id: int) -> bool:
    """检查用户是否为管理员"""
    try:
        result = await db_fetchval("SELECT is_admin FROM users WHERE id = $1", user_id)
        return bool(result)
    except Exception as e:
        logger.error(f"检查管理员权限失败: {e}")
        return False

async def get_setting(key: str) -> Optional[str]:
    """获取系统设置"""
    try:
        return await db_fetchval("SELECT value FROM settings WHERE key = $1", key.lower())
    except Exception as e:
        logger.error(f"获取设置失败: {e}")
        return None

async def set_setting(key: str, value: str, user_id: int) -> bool:
    """设置系统配置"""
    try:
        await db_execute("""
            INSERT INTO settings (key, value, updated_by) 
            VALUES ($1, $2, $3) 
            ON CONFLICT (key) DO UPDATE SET 
                value = $2, 
                updated_by = $3, 
                updated_at = NOW()
        """, key.lower(), value, user_id)
        return True
    except Exception as e:
        logger.error(f"设置配置失败: {e}")
        return False

async def get_user_by_username(username: str) -> Optional[Dict]:
    """通过用户名查找用户"""
    try:
        return await db_fetch_one("SELECT * FROM users WHERE lower(username) = lower($1)", username.lower())
    except Exception as e:
        logger.error(f"查找用户失败: {e}")
        return None
