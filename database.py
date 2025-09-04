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
    """创建数据库表"""
    async with db_pool.acquire() as conn:
        # 检查并修复表结构
        try:
            # 修复 users 表
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_activity TIMESTAMP WITH TIME ZONE DEFAULT NOW()")
            
            # 修复 tags 表  
            await conn.execute("ALTER TABLE tags ADD COLUMN IF NOT EXISTS name TEXT")
            await conn.execute("ALTER TABLE tags ADD COLUMN IF NOT EXISTS type TEXT")
            
            # 如果是旧字段名，进行数据迁移
            try:
                # 迁移 users 表数据
                await conn.execute("UPDATE users SET first_name = name WHERE first_name IS NULL AND name IS NOT NULL")
                await conn.execute("UPDATE users SET last_activity = last_active WHERE last_activity IS NULL AND last_active IS NOT NULL")
                
                # 迁移 tags 表数据
                await conn.execute("UPDATE tags SET name = tag_name WHERE name IS NULL AND tag_name IS NOT NULL")
                await conn.execute("UPDATE tags SET type = tag_type WHERE type IS NULL AND tag_type IS NOT NULL")
                
            except Exception as migration_error:
                logger.info(f"数据迁移跳过（可能是新表）: {migration_error}")
            
            # 修复 reputations 表
            await conn.execute("ALTER TABLE reputations ADD COLUMN IF NOT EXISTS target_id BIGINT")
            await conn.execute("ALTER TABLE reputations ADD COLUMN IF NOT EXISTS voter_id BIGINT") 
            
            try:
                # 迁移 reputations 表数据
                await conn.execute("UPDATE reputations SET target_id = target_user_id WHERE target_id IS NULL AND target_user_id IS NOT NULL")
                await conn.execute("UPDATE reputations SET voter_id = voter_user_id WHERE voter_id IS NULL AND voter_user_id IS NOT NULL")
            except Exception as migration_error:
                logger.info(f"reputations 迁移跳过: {migration_error}")
            
            # 修复 favorites 表
            await conn.execute("ALTER TABLE favorites ADD COLUMN IF NOT EXISTS target_id BIGINT")
            
            try:
                # 迁移 favorites 表数据
                await conn.execute("UPDATE favorites SET target_id = favorite_user_id WHERE target_id IS NULL AND favorite_user_id IS NOT NULL")
            except Exception as migration_error:
                logger.info(f"favorites 迁移跳过: {migration_error}")
                
        except Exception as e:
            logger.warning(f"表结构修复过程中的警告: {e}")
        
        # 创建基础表（如果不存在）
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
                name TEXT NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('recommend', 'block')),
                created_by BIGINT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                UNIQUE(name)
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
        
        # 插入默认设置（不包括默认箴言）
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
        
        # 插入默认标签
        await conn.execute("""
            INSERT INTO tags (name, type) VALUES 
            ('靠谱', 'recommend'),
            ('诚信', 'recommend'),
            ('专业', 'recommend'),
            ('友善', 'recommend'),
            ('负责', 'recommend'),
            ('不靠谱', 'block'),
            ('欺骗', 'block'),
            ('失信', 'block'),
            ('态度差', 'block'),
            ('不负责', 'block')
            ON CONFLICT (name) DO NOTHING
        """)
        
        logger.info("✅ 数据库表创建完成")

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
    """获取随机便签"""
    try:
        return await db_fetchval("SELECT content FROM mottos ORDER BY RANDOM() LIMIT 1")
    except Exception as e:
        logger.debug(f"获取便签失败（可能为空）: {e}")
        return None

async def get_all_mottos() -> List[Dict]:
    """获取所有便签"""
    try:
        return await db_fetch_all("SELECT * FROM mottos ORDER BY created_at DESC")
    except Exception as e:
        logger.error(f"获取所有便签失败: {e}")
        return []

async def add_mottos_batch(mottos: List[str], user_id: int) -> int:
    """批量添加便签"""
    added_count = 0
    try:
        for motto in mottos:
            try:
                await db_execute(
                    "INSERT INTO mottos (content, created_by) VALUES ($1, $2)",
                    motto, user_id
                )
                added_count += 1
            except:
                # 忽略重复的便签
                continue
    except Exception as e:
        logger.error(f"批量添加便签失败: {e}")
    
    return added_count
