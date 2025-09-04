import asyncio
import logging
from os import environ
from contextlib import asynccontextmanager

import asyncpg

logger = logging.getLogger(__name__)
DB_URL = environ.get("DATABASE_URL")
_pool = None

async def init_pool():
    global _pool
    try:
        _pool = await asyncpg.create_pool(DB_URL)
        logger.info("✅ 数据库连接池初始化成功")
        return _pool
    except Exception as e:
        logger.critical(f"❌ 初始化数据库连接池失败: {e}", exc_info=True)
        raise

@asynccontextmanager
async def db_transaction():
    if not _pool:
        await init_pool()
    async with _pool.acquire() as conn:
        async with conn.transaction():
            yield conn

async def db_fetch_one(query, *args):
    if not _pool:
        await init_pool()
    async with _pool.acquire() as conn:
        return await conn.fetchrow(query, *args)

async def db_fetch_all(query, *args):
    if not _pool:
        await init_pool()
    async with _pool.acquire() as conn:
        return await conn.fetch(query, *args)

async def db_execute(query, *args):
    if not _pool:
        await init_pool()
    async with _pool.acquire() as conn:
        return await conn.execute(query, *args)

async def create_tables():
    async with db_transaction() as conn:
        # 用户表
        await conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            is_admin BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # 声誉标签表
        await conn.execute('''
        CREATE TABLE IF NOT EXISTS tags (
            id SERIAL PRIMARY KEY,
            tag_type TEXT NOT NULL,  -- 'recommend' 或 'block' 或 'quote'
            content TEXT NOT NULL,
            created_by BIGINT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
        ''')

        # 声誉评价表
        await conn.execute('''
        CREATE TABLE IF NOT EXISTS reputation (
            id SERIAL PRIMARY KEY,
            target_id BIGINT NOT NULL,
            voter_id BIGINT NOT NULL,
            tag_id INTEGER NOT NULL,
            is_positive BOOLEAN NOT NULL,  -- TRUE为正面评价，FALSE为负面评价
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (target_id) REFERENCES users(id),
            FOREIGN KEY (voter_id) REFERENCES users(id),
            FOREIGN KEY (tag_id) REFERENCES tags(id),
            CONSTRAINT unique_vote UNIQUE (target_id, voter_id, tag_id)
        )
        ''')

        # 收藏表
        await conn.execute('''
        CREATE TABLE IF NOT EXISTS favorites (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            target_id BIGINT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (target_id) REFERENCES users(id),
            CONSTRAINT unique_favorite UNIQUE (user_id, target_id)
        )
        ''')
        
        # 系统设置表
        await conn.execute('''
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # 箴言引用统计表
        await conn.execute('''
        CREATE TABLE IF NOT EXISTS quote_stats (
            quote_id INTEGER PRIMARY KEY,
            usage_count INTEGER DEFAULT 0,
            last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (quote_id) REFERENCES tags(id)
        )
        ''')

        logger.info("✅ 数据库表结构初始化完成")
