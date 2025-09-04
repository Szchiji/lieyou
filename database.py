import logging
import asyncio
import asyncpg
from os import environ
from contextlib import asynccontextmanager
from datetime import datetime

logger = logging.getLogger(__name__)

# 数据库连接池
pool = None

async def init_pool():
    """初始化数据库连接池"""
    global pool
    try:
        db_url = environ.get("DATABASE_URL")
        if not db_url:
            raise ValueError("环境变量 DATABASE_URL 未设置")
        
        # 创建连接池
        pool = await asyncpg.create_pool(db_url)
        logger.info("✅ 数据库连接池初始化成功")
    except Exception as e:
        logger.critical(f"❌ 数据库连接池初始化失败: {e}", exc_info=True)
        raise

@asynccontextmanager
async def db_transaction():
    """提供带有事务的数据库连接的上下文管理器"""
    if pool is None:
        raise RuntimeError("数据库连接池未初始化")
    
    async with pool.acquire() as connection:
        transaction = connection.transaction()
        await transaction.start()
        try:
            yield connection
            await transaction.commit()
        except Exception:
            await transaction.rollback()
            raise

async def update_user_activity(user_id, username=None):
    """更新用户活动时间并可选地更新用户名"""
    try:
        async with db_transaction() as conn:
            if username:
                await conn.execute(
                    """
                    INSERT INTO users (id, username, last_active) 
                    VALUES ($1, $2, NOW()) 
                    ON CONFLICT (id) DO UPDATE 
                    SET last_active = NOW(), username = $2
                    """, 
                    user_id, username
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO users (id, last_active) 
                    VALUES ($1, NOW()) 
                    ON CONFLICT (id) DO UPDATE 
                    SET last_active = NOW()
                    """, 
                    user_id
                )
    except Exception as e:
        logger.error(f"更新用户活动失败: {e}", exc_info=True)

async def create_tables():
    """创建所需的数据库表"""
    try:
        async with db_transaction() as conn:
            # 用户表
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY,
                    username TEXT,
                    is_admin BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    last_active TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            # 声誉表（用户对用户的评价）
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS reputations (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    target_id BIGINT NOT NULL,
                    is_positive BOOLEAN NOT NULL,
                    comment TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(user_id, target_id),
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY(target_id) REFERENCES users(id) ON DELETE CASCADE
                )
            ''')
            
            # 标签表
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tags (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    tag_type TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(name, tag_type)
                )
            ''')
            
            # 声誉标签关联表
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS reputation_tags (
                    reputation_id INTEGER REFERENCES reputations(id) ON DELETE CASCADE,
                    tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
                    PRIMARY KEY (reputation_id, tag_id)
                )
            ''')
            
            # 收藏表（用户收藏的其他用户）
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS favorites (
                    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
                    target_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (user_id, target_id)
                )
            ''')
            
            # 系统设置表
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            # 插入默认设置
            await conn.execute('''
                INSERT INTO settings (key, value) VALUES
                ('min_reputation_votes', '3'),
                ('max_daily_votes', '10'),
                ('leaderboard_min_votes', '3'),
                ('leaderboard_size', '10')
                ON CONFLICT (key) DO NOTHING
            ''')
            
            # 箴言表
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS mottos (
                    id SERIAL PRIMARY KEY,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            logger.info("✅ 数据库表创建/更新成功")
            
    except Exception as e:
        logger.critical(f"❌ 创建数据库表失败: {e}", exc_info=True)
        raise
