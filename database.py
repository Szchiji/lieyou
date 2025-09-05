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
        # 步骤 1: 创建所有表和新列（如果它们不存在）
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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reputations (
                id SERIAL PRIMARY KEY,
                target_id BIGINT NOT NULL,
                voter_id BIGINT NOT NULL,
                is_positive BOOLEAN NOT NULL,
                tag_ids INTEGER[],
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
        # 已移除 mottos 表的创建
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS erasure_records (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                type TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)

        # 步骤 2: 执行数据迁移（如果需要）
        logger.info("步骤 2: 执行数据迁移（如果需要）...")
        # ... (迁移逻辑保持不变)

        # 步骤 3: 清理旧的数据库列
        logger.info("步骤 3: 清理旧的数据库列...")
        await conn.execute("ALTER TABLE tags DROP COLUMN IF EXISTS tag_name")
        await conn.execute("ALTER TABLE tags DROP COLUMN IF EXISTS tag_type")
        await conn.execute("ALTER TABLE reputations DROP COLUMN IF EXISTS target_user_id")
        await conn.execute("ALTER TABLE reputations DROP COLUMN IF EXISTS voter_user_id")
        await conn.execute("ALTER TABLE users DROP COLUMN IF EXISTS name")
        await conn.execute("ALTER TABLE users DROP COLUMN IF EXISTS last_active")
        await conn.execute("ALTER TABLE favorites DROP COLUMN IF EXISTS favorite_user_id")
        
        # 步骤 4: 插入默认数据
        logger.info("步骤 4: 插入默认设置...")
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
        
        # 已移除默认标签的插入
        
        logger.info("✅ 数据库表初始化/迁移完成")

# === 业务逻辑函数 ===

async def get_or_create_user_by_username(username: str) -> Optional[Dict]:
    """通过用户名获取用户，如果不存在则创建虚拟用户记录"""
    try:
        # 尝试通过用户名查找
        target_user = await get_user_by_username(username)
        if target_user:
            return target_user

        # 如果用户不存在，创建虚拟记录
        logger.info(f"用户 @{username} 不存在，将为其创建虚拟档案...")
        # 使用用户名的哈希值生成一个稳定且唯一的虚拟ID
        virtual_user_id = abs(hash(username))
        
        await db_execute(
            "INSERT INTO users (id, username, first_name) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
            virtual_user_id, username, f"@{username}"
        )
        
        # 返回新创建的虚拟用户信息
        return {'id': virtual_user_id, 'username': username, 'first_name': f"@{username}"}
    except Exception as e:
        logger.error(f"获取或创建用户 @{username} 时失败: {e}", exc_info=True)
        return None


async def get_all_tags_by_type(tag_type: str) -> List[Dict]:
    """根据类型获取所有标签"""
    return await db_fetch_all("SELECT id, name FROM tags WHERE type = $1 ORDER BY name", tag_type)

# ... (其他业务逻辑函数保持不变, 已移除便签相关函数)
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
        return await db_fetchval("SELECT value FROM settings WHERE key = $1", key)
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
        """, key, value, user_id)
        return True
    except Exception as e:
        logger.error(f"设置配置失败: {e}")
        return False

async def get_user_by_username(username: str) -> Optional[Dict]:
    """通过用户名查找用户"""
    try:
        # 查询时忽略大小写
        return await db_fetch_one("SELECT * FROM users WHERE lower(username) = lower($1)", username)
    except Exception as e:
        logger.error(f"查找用户失败: {e}")
        return None
