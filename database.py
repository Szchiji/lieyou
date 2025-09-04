import asyncpg
import logging
from os import environ
from datetime import datetime

logger = logging.getLogger(__name__)
pool = None

async def init_pool():
    global pool
    if pool: return
    pool = await asyncpg.create_pool(
        dsn=environ.get("DATABASE_URL"),
        min_size=1,
        max_size=10,
        command_timeout=60,
    )
    logger.info("✅ 数据库连接池已成功初始化。")

async def create_tables():
    logger.info("✅ (启动流程) 正在检查并创建/迁移所有数据表...")
    await init_pool()
    async with pool.acquire() as conn:
        # users
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY,
                is_admin BOOLEAN DEFAULT FALSE,
                username TEXT,
                first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
    async with pool.acquire() as conn:
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;")
            logger.info("✅ (数据库迁移) 'users' 表字段检查完成。")
        except Exception as e:
            logger.warning(f"(数据库迁移) 添加字段失败，可能已存在: {e}")
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reputation_profiles (
                username TEXT PRIMARY KEY,
                recommend_count INTEGER DEFAULT 0,
                block_count INTEGER DEFAULT 0,
                first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
    async with pool.acquire() as conn:
        try:
            await conn.execute("ALTER TABLE reputation_profiles ADD COLUMN IF NOT EXISTS first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;")
            await conn.execute("ALTER TABLE reputation_profiles ADD COLUMN IF NOT EXISTS last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;")
            logger.info("✅ (数据库迁移) 'reputation_profiles' 表字段检查完成。")
        except Exception as e:
            logger.warning(f"(数据库迁移) 添加字段失败，可能已存在: {e}")
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                id SERIAL PRIMARY KEY,
                tag_name TEXT NOT NULL,
                type TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (tag_name, type)
            );
        """)
    async with pool.acquire() as conn:
        try:
            await conn.execute("ALTER TABLE tags ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;")
            logger.info("✅ (数据库迁移) 'tags' 表字段检查完成。")
        except Exception as e:
            logger.warning(f"(数据库迁移) 添加字段失败，可能已存在: {e}")
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS votes (
                id SERIAL PRIMARY KEY,
                nominator_id BIGINT NOT NULL,
                nominee_username TEXT NOT NULL,
                vote_type TEXT NOT NULL,
                tag_id INTEGER REFERENCES tags(id) ON DELETE SET NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                favorite_username TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (user_id, favorite_username)
            );
        """)
    async with pool.acquire() as conn:
        try:
            await conn.execute("ALTER TABLE favorites ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;")
            logger.info("✅ (数据库迁移) 'favorites' 表字段检查完成。")
        except Exception as e:
            logger.warning(f"(数据库迁移) 添加字段失败，可能已存在: {e}")
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
    async with pool.acquire() as conn:
        try:
            await conn.execute("ALTER TABLE settings ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;")
            logger.info("✅ (数据库迁移) 'settings' 表字段检查完成。")
        except Exception as e:
            logger.warning(f"(数据库迁移) 添加字段失败，可能已存在: {e}")
    
    # 新增：prayers表，用于存储用户祈祷内容和回应
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS prayers (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                prayer_text TEXT NOT NULL,
                response_text TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                response_at TIMESTAMP WITH TIME ZONE
            );
        """)
    
    # 初始化默认设置
    await initialize_default_settings()
    logger.info("✅ (启动流程) 所有数据表检查/创建/迁移完毕。")

async def initialize_default_settings():
    """初始化默认系统设置"""
    default_settings = {
        'leaderboard_cache_ttl': '300',  # 5分钟缓存
        'max_prayers_per_day': '3',      # 每用户每日最大祈祷次数
        'prayer_cooldown': '3600',       # 祈祷冷却时间（秒）
    }
    
    async with db_transaction() as conn:
        for key, value in default_settings.items():
            await conn.execute("""
                INSERT INTO settings (key, value) 
                VALUES ($1, $2)
                ON CONFLICT (key) DO NOTHING
            """, key, value)

# 数据库事务上下文管理器
from contextlib import asynccontextmanager
@asynccontextmanager
async def db_transaction():
    if not pool:
        await init_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn

async def update_user_activity(user_id: int, username: str = None):
    """更新用户活动时间"""
    try:
        async with db_transaction() as conn:
            if username:
                await conn.execute("""
                    INSERT INTO users (id, username, last_active) 
                    VALUES ($1, $2, CURRENT_TIMESTAMP) 
                    ON CONFLICT (id) DO UPDATE 
                    SET username = $2, last_active = CURRENT_TIMESTAMP
                """, user_id, username)
            else:
                await conn.execute("""
                    UPDATE users SET last_active = CURRENT_TIMESTAMP 
                    WHERE id = $1
                """, user_id)
    except Exception as e:
        logger.error(f"更新用户活动失败: {e}", exc_info=True)

async def get_system_stats():
    """获取系统统计数据"""
    async with db_transaction() as conn:
        stats = {}
        
        # 总用户数
        stats['total_users'] = await conn.fetchval("SELECT COUNT(*) FROM users")
        
        # 总档案数
        stats['total_profiles'] = await conn.fetchval("SELECT COUNT(*) FROM reputation_profiles")
        
        # 总投票数
        stats['total_votes'] = await conn.fetchval("SELECT COUNT(*) FROM votes")
        
        # 标签数量
        stats['recommend_tags'] = await conn.fetchval("SELECT COUNT(*) FROM tags WHERE type = 'recommend'")
        stats['block_tags'] = await conn.fetchval("SELECT COUNT(*) FROM tags WHERE type = 'block'")
        
        # 今日活跃统计
        today = datetime.now().date()
        stats['today_votes'] = await conn.fetchval(
            "SELECT COUNT(*) FROM votes WHERE DATE(created_at) = $1", 
            today
        )
        
        # 最活跃用户
        most_active = await conn.fetch("""
            SELECT nominee_username, COUNT(*) as vote_count 
            FROM votes 
            GROUP BY nominee_username 
            ORDER BY vote_count DESC 
            LIMIT 1
        """)
        stats['most_active_user'] = most_active[0]['nominee_username'] if most_active else None
        
        # 今日祈祷统计
        stats['today_prayers'] = await conn.fetchval(
            "SELECT COUNT(*) FROM prayers WHERE DATE(created_at) = $1",
            today
        )
        
        return stats
