import logging
import asyncpg
from os import environ
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

POOL = None

async def init_pool():
    global POOL
    if POOL: return
    try:
        POOL = await asyncpg.create_pool(dsn=environ.get("DATABASE_URL"))
        logger.info("✅ 异步数据库连接池初始化成功。")
    except Exception as e:
        logger.critical(f"❌ 数据库连接池初始化失败: {e}", exc_info=True)
        raise

@asynccontextmanager
async def db_cursor():
    if not POOL: await init_pool()
    conn = None
    try:
        conn = await POOL.acquire()
        yield conn
    except Exception as e:
        logger.error(f"数据库操作中发生错误: {e}", exc_info=True)
        raise
    finally:
        if conn: await POOL.release(conn)

async def create_tables():
    """最终的、为“符号信誉系统”设计的数据库初始化程序。"""
    async with db_cursor() as cur:
        logger.info("正在执行最终的数据库结构审查与重建...")
        try:
            # --- 1. 为管理员功能保留一个简单的 users 表 ---
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY,
                    is_admin BOOLEAN DEFAULT FALSE
                );
            """)

            # --- 2. 核心改造：创建“符号档案”表 ---
            # 为了确保干净，先删除所有可能存在的旧表
            await cur.execute("DROP TABLE IF EXISTS favorites CASCADE;")
            await cur.execute("DROP TABLE IF EXISTS votes CASCADE;")
            await cur.execute("DROP TABLE IF EXISTS reputation_profiles CASCADE;")
            # 也删除旧的 users 表的列，以防万一
            try:
                await cur.execute("ALTER TABLE users DROP COLUMN username;")
                await cur.execute("ALTER TABLE users DROP COLUMN full_name;")
                await cur.execute("ALTER TABLE users DROP COLUMN recommend_count;")
                await cur.execute("ALTER TABLE users DROP COLUMN block_count;")
            except asyncpg.exceptions.UndefinedColumnError:
                pass

            logger.info("已移除所有旧的、与用户相关的表和列，准备重建为“符号系统”。")
            
            await cur.execute("""
                CREATE TABLE reputation_profiles (
                    username VARCHAR(255) PRIMARY KEY,
                    recommend_count INT NOT NULL DEFAULT 0,
                    block_count INT NOT NULL DEFAULT 0
                );
            """)
            logger.info("🎉 已成功创建核心的 `reputation_profiles` 表！")

            # --- 3. 标签表 (保持不变) ---
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id SERIAL PRIMARY KEY,
                    tag_name VARCHAR(255) UNIQUE NOT NULL,
                    type VARCHAR(50) NOT NULL CHECK (type IN ('recommend', 'block'))
                );
            """)

            # --- 4. 投票表 (改造以适应新核心) ---
            await cur.execute("""
                CREATE TABLE votes (
                    id SERIAL PRIMARY KEY,
                    nominator_id BIGINT NOT NULL,
                    nominee_username VARCHAR(255) REFERENCES reputation_profiles(username) ON DELETE CASCADE,
                    tag_id INT REFERENCES tags(id) ON DELETE CASCADE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(nominator_id, nominee_username, tag_id)
                );
            """)
            logger.info("🎉 已成功创建适配“符号系统”的 `votes` 表！")

            logger.info("✅✅✅ 所有数据库表都已达到最终的、完美的“符号信誉系统”状态！")
        except Exception as e:
            logger.error(f"❌ 在最终的数据库重建过程中发生严重错误: {e}", exc_info=True)
            raise
