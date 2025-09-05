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
    """更新用户活动时间"""
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
        # ------------------------------------------------
        logger.info("步骤 1: 确保所有表和列都存在...")
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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS mottos (
                id SERIAL PRIMARY KEY,
                content TEXT NOT NULL UNIQUE,
                created_by BIGINT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
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

        # 步骤 2: 执行从旧结构到新结构的数据迁移
        # ------------------------------------------------
        logger.info("步骤 2: 执行数据迁移（如果需要）...")
        try:
            # 迁移 tags 表: 从 tag_name/tag_type -> name/type
            if await conn.fetchval("SELECT to_regclass('tags') IS NOT NULL"):
                 if await conn.fetchval("SELECT 1 FROM information_schema.columns WHERE table_name='tags' AND column_name='tag_name'"):
                    logger.info("检测到旧列 'tag_name'，开始迁移 tags 表...")
                    await conn.execute("UPDATE tags SET name = tag_name WHERE name IS NULL AND tag_name IS NOT NULL")
                    await conn.execute("UPDATE tags SET type = tag_type WHERE type IS NULL AND tag_type IS NOT NULL")
                    logger.info("tags 表数据迁移完成。")
            
            # 迁移 reputations 表: 从 ...user_id -> ...id
            if await conn.fetchval("SELECT to_regclass('reputations') IS NOT NULL"):
                if await conn.fetchval("SELECT 1 FROM information_schema.columns WHERE table_name='reputations' AND column_name='target_user_id'"):
                    logger.info("检测到旧列 'target_user_id'，开始迁移 reputations 表...")
                    await conn.execute("ALTER TABLE reputations ADD COLUMN IF NOT EXISTS target_id BIGINT")
                    await conn.execute("ALTER TABLE reputations ADD COLUMN IF NOT EXISTS voter_id BIGINT")
                    await conn.execute("UPDATE reputations SET target_id = target_user_id WHERE target_id IS NULL AND target_user_id IS NOT NULL")
                    await conn.execute("UPDATE reputations SET voter_id = voter_user_id WHERE voter_id IS NULL AND voter_user_id IS NOT NULL")
                    logger.info("reputations 表数据迁移完成。")

        except Exception as e:
            logger.error(f"数据迁移过程中发生错误: {e}", exc_info=True)
            # 不抛出异常，允许应用继续启动，但记录严重错误

        # 步骤 3: 安全地删除已迁移的旧列
        # ------------------------------------------------
        logger.info("步骤 3: 清理旧的数据库列...")
        await conn.execute("ALTER TABLE tags DROP COLUMN IF EXISTS tag_name")
        await conn.execute("ALTER TABLE tags DROP COLUMN IF EXISTS tag_type")
        await conn.execute("ALTER TABLE reputations DROP COLUMN IF EXISTS target_user_id")
        await conn.execute("ALTER TABLE reputations DROP COLUMN IF EXISTS voter_user_id")
        # 其他可能存在的旧列...
        await conn.execute("ALTER TABLE users DROP COLUMN IF EXISTS name")
        await conn.execute("ALTER TABLE users DROP COLUMN IF EXISTS last_active")
        await conn.execute("ALTER TABLE favorites DROP COLUMN IF EXISTS favorite_user_id")
        
        # 步骤 4: 插入默认数据（现在应该是安全的）
        # ------------------------------------------------
        logger.info("步骤 4: 插入默认设置和标签...")
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
        
        await conn.execute("""
            INSERT INTO tags (name, type) VALUES 
            ('靠谱', 'recommend'), ('诚信', 'recommend'), ('专业', 'recommend'),
            ('友善', 'recommend'), ('负责', 'recommend'), ('不靠谱', 'block'),
            ('欺骗', 'block'), ('失信', 'block'), ('态度差', 'block'), ('不负责', 'block')
            ON CONFLICT (name) DO NOTHING
        """)
        
        logger.info("✅ 数据库表初始化/迁移完成")

# === 业务逻辑函数 ===

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
        return await db_fetch_one("SELECT * FROM users WHERE username = $1", username)
    except Exception as e:
        logger.error(f"查找用户失败: {e}")
        return None

async def get_random_motto() -> Optional[str]:
    """获取随机箴言"""
    try:
        return await db_fetchval("SELECT content FROM mottos ORDER BY RANDOM() LIMIT 1")
    except Exception as e:
        logger.debug(f"获取箴言失败（可能为空）: {e}")
        return None

async def get_all_mottos() -> List[Dict]:
    """获取所有箴言"""
    try:
        return await db_fetch_all("SELECT * FROM mottos ORDER BY created_at DESC")
    except Exception as e:
        logger.error(f"获取所有箴言失败: {e}")
        return []

async def add_mottos_batch(mottos: List[str], user_id: int) -> int:
    """批量添加箴言（高效版）"""
    data_to_insert = [(motto, user_id) for motto in mottos]
    if not data_to_insert:
        return 0

    try:
        async with db_pool.acquire() as conn:
            # 使用 executemany 进行批量插入，ON CONFLICT 优雅地处理重复项
            result = await conn.executemany(
                "INSERT INTO mottos (content, created_by) VALUES ($1, $2) ON CONFLICT (content) DO NOTHING",
                data_to_insert
            )
            # 解析 "INSERT 0 N" 返回值获取成功插入的行数
            return int(result.split()[-1])
    except (Exception, ValueError, IndexError) as e:
        logger.error(f"批量添加箴言失败: {e}")
        return 0
