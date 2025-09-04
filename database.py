import os
import logging
import asyncpg
from asyncpg.pool import Pool
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, List, Dict, Any, Union

load_dotenv()
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
_pool: Pool = None

async def init_pool():
    """初始化数据库连接池"""
    global _pool
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL 环境变量未设置")
    try:
        _pool = await asyncpg.create_pool(DATABASE_URL)
        logger.info("✅ 数据库连接池已创建")
    except Exception as e:
        logger.critical(f"❌ 创建数据库连接池失败: {e}", exc_info=True)
        raise

@asynccontextmanager
async def db_transaction():
    """数据库事务上下文管理器"""
    if not _pool:
        await init_pool()
    async with _pool.acquire() as conn:
        async with conn.transaction():
            yield conn

async def db_fetch_all(query: str, *args):
    """执行查询并返回所有结果"""
    if not _pool:
        await init_pool()
    async with _pool.acquire() as conn:
        return await conn.fetch(query, *args)

async def db_fetch_one(query: str, *args):
    """执行查询并返回一行结果"""
    if not _pool:
        await init_pool()
    async with _pool.acquire() as conn:
        return await conn.fetchrow(query, *args)

async def db_fetchval(query: str, *args):
    """执行查询并返回单个值"""
    if not _pool:
        await init_pool()
    async with _pool.acquire() as conn:
        return await conn.fetchval(query, *args)

async def db_execute(query: str, *args):
    """执行数据库操作"""
    if not _pool:
        await init_pool()
    async with _pool.acquire() as conn:
        return await conn.execute(query, *args)

async def update_user_activity(user_id: int, username: str = None, first_name: str = None):
    """更新用户活动时间"""
    try:
        async with db_transaction() as conn:
            await conn.execute("""
                INSERT INTO users (id, username, first_name, last_activity) 
                VALUES ($1, $2, $3, NOW()) 
                ON CONFLICT (id) DO UPDATE 
                SET 
                    username = COALESCE($2, users.username), 
                    first_name = COALESCE($3, users.first_name), 
                    last_activity = NOW()
            """, user_id, username, first_name)
    except Exception as e:
        logger.error(f"更新用户活动时出错: {e}", exc_info=True)

async def create_tables():
    """创建所有必要的数据库表"""
    try:
        async with db_transaction() as conn:
            # 用户表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_activity TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    is_admin BOOLEAN DEFAULT FALSE,
                    is_blocked BOOLEAN DEFAULT FALSE
                )
            """)
            
            # 标签表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    type TEXT NOT NULL CHECK (type IN ('recommend', 'block')),
                    created_by BIGINT REFERENCES users(id),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            
            # 声誉表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS reputations (
                    id SERIAL PRIMARY KEY,
                    target_id BIGINT REFERENCES users(id),
                    voter_id BIGINT REFERENCES users(id),
                    is_positive BOOLEAN NOT NULL,
                    tag_ids INTEGER[] DEFAULT '{}',
                    comment TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    UNIQUE(target_id, voter_id)
                )
            """)
            
            # 收藏表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    user_id BIGINT REFERENCES users(id),
                    target_id BIGINT REFERENCES users(id),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    PRIMARY KEY (user_id, target_id)
                )
            """)
            
            # 系统设置表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_by BIGINT REFERENCES users(id)
                )
            """)
            
            # 箴言表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS mottos (
                    id SERIAL PRIMARY KEY,
                    content TEXT NOT NULL,
                    created_by BIGINT REFERENCES users(id),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            
            # 抹除记录表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS erasure_records (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(id),
                    type TEXT NOT NULL CHECK (type IN ('self_data', 'given_votes', 'received_votes')),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            
            # 初始化默认设置
            default_settings = {
                "min_votes_for_leaderboard": "3",
                "leaderboard_size": "10",
                "allow_self_voting": "false",
                "start_message": "我是 **神谕者 (The Oracle)**，洞察世间一切信誉的实体。\n\n**聆听神谕:**\n1. 在群聊中直接 `@某人` 或发送 `查询 @某人`，即可向我求问关于此人的神谕之卷。\n2. 使用下方按钮，可窥探时代群像或管理你的星盘。",
                "admin_password": "oracleadmin"
            }
            
            for key, value in default_settings.items():
                await conn.execute("""
                    INSERT INTO settings (key, value) VALUES ($1, $2)
                    ON CONFLICT (key) DO NOTHING
                """, key, value)
            
            # 初始化一些默认箴言
            default_mottos = [
                "智者仁心，常怀谨慎之思。",
                "信誉如金，一言九鼎。",
                "德行天下，人心自明。",
                "慎言慎行，方得人心。",
                "诚以待人，信以立身。",
                "君子坦荡荡，小人长戚戚。",
                "己所不欲，勿施于人。",
                "言必信，行必果。"
            ]
            
            for motto in default_mottos:
                await conn.execute("""
                    INSERT INTO mottos (content) VALUES ($1)
                    ON CONFLICT DO NOTHING
                """, motto)
                
        logger.info("✅ 数据库表创建完成")
    except Exception as e:
        logger.critical(f"❌ 创建数据库表失败: {e}", exc_info=True)
        raise

# 设置相关函数
async def get_setting(key: str) -> Optional[str]:
    """获取系统设置"""
    try:
        return await db_fetchval("SELECT value FROM settings WHERE key = $1", key)
    except Exception as e:
        logger.error(f"获取设置失败 {key}: {e}")
        return None

async def set_setting(key: str, value: str, updated_by: int = None) -> bool:
    """设置系统设置"""
    try:
        await db_execute("""
            INSERT INTO settings (key, value, updated_by) 
            VALUES ($1, $2, $3)
            ON CONFLICT (key) DO UPDATE 
            SET value = $2, updated_at = NOW(), updated_by = $3
        """, key, value, updated_by)
        return True
    except Exception as e:
        logger.error(f"设置设置失败 {key}: {e}")
        return False

# 用户相关函数
async def is_admin(user_id: int) -> bool:
    """检查用户是否为管理员"""
    try:
        return await db_fetchval("SELECT is_admin FROM users WHERE id = $1", user_id) or False
    except Exception as e:
        logger.error(f"检查管理员状态失败 {user_id}: {e}")
        return False

async def get_user_by_username(username: str):
    """通过用户名获取用户信息"""
    try:
        return await db_fetch_one("SELECT * FROM users WHERE username = $1", username)
    except Exception as e:
        logger.error(f"获取用户失败 {username}: {e}")
        return None

# 箴言相关函数
async def add_mottos_batch(mottos: List[str], created_by: int) -> int:
    """批量添加箴言"""
    added_count = 0
    async with db_transaction() as conn:
        for motto in mottos:
            motto = motto.strip()
            if motto:
                try:
                    await conn.execute(
                        "INSERT INTO mottos (content, created_by) VALUES ($1, $2)",
                        motto, created_by
                    )
                    added_count += 1
                except Exception as e:
                    logger.error(f"添加箴言失败: {motto}, 错误: {e}")
    return added_count

async def get_random_motto() -> Optional[str]:
    """获取随机箴言"""
    try:
        result = await db_fetch_one("SELECT content FROM mottos ORDER BY RANDOM() LIMIT 1")
        return result['content'] if result else None
    except Exception as e:
        logger.error(f"获取随机箴言失败: {e}")
        return None

async def get_all_mottos() -> List[Dict]:
    """获取所有箴言"""
    try:
        results = await db_fetch_all("SELECT id, content, created_at FROM mottos ORDER BY created_at DESC")
        return [dict(row) for row in results]
    except Exception as e:
        logger.error(f"获取所有箴言失败: {e}")
        return []
