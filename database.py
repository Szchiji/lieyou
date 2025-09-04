import os
import logging
import asyncpg
import psycopg2
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any, Union, Tuple

load_dotenv()
logger = logging.getLogger(__name__)
DB_URL = os.environ.get("DATABASE_URL")
if not DB_URL:
    raise ValueError("环境变量 DATABASE_URL 未设置")

_pool = None

async def init_pool():
    global _pool
    try:
        _pool = await asyncpg.create_pool(DB_URL)
        logger.info("✅ 数据库连接池初始化成功")
    except Exception as e:
        logger.error(f"❌ 数据库连接池初始化失败: {e}", exc_info=True)
        raise

@asynccontextmanager
async def db_transaction():
    """事务上下文管理器"""
    if not _pool:
        await init_pool()
    async with _pool.acquire() as conn:
        async with conn.transaction():
            yield conn

async def db_execute(query: str, *args):
    """执行数据库操作并返回受影响的行数"""
    if not _pool:
        await init_pool()
    async with _pool.acquire() as conn:
        return await conn.execute(query, *args)

async def db_fetch(query: str, *args):
    """执行查询并返回所有结果"""
    if not _pool:
        await init_pool()
    async with _pool.acquire() as conn:
        return await conn.fetch(query, *args)

async def db_fetchrow(query: str, *args):
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

async def create_tables():
    """创建所有必要的数据库表"""
    queries = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            username TEXT,
            first_seen TIMESTAMP DEFAULT NOW(),
            last_active TIMESTAMP DEFAULT NOW(),
            is_admin BOOLEAN DEFAULT FALSE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS tags (
            id SERIAL PRIMARY KEY,
            tag_type TEXT NOT NULL CHECK (tag_type IN ('recommend', 'block')),
            content TEXT NOT NULL,
            created_by BIGINT REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS nominations (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id),
            nominee_id BIGINT NOT NULL REFERENCES users(id),
            tag_id INTEGER REFERENCES tags(id),
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, nominee_id, tag_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS user_favorites (
            user_id BIGINT NOT NULL REFERENCES users(id),
            nominee_id BIGINT NOT NULL REFERENCES users(id),
            added_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (user_id, nominee_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT NOW(),
            updated_by BIGINT REFERENCES users(id)
        )
        """
    ]
    
    try:
        async with db_transaction() as conn:
            for query in queries:
                await conn.execute(query)
        logger.info("✅ 数据库表创建或验证完成")
    except Exception as e:
        logger.error(f"❌ 创建数据库表时出错: {e}", exc_info=True)
        raise

async def update_user_activity(user_id: int, username: str = None):
    """更新用户活动时间并创建用户记录（如果不存在）"""
    try:
        query = """
            INSERT INTO users (id, username, last_active)
            VALUES ($1, $2, NOW())
            ON CONFLICT (id) DO UPDATE 
            SET last_active = NOW(), 
                username = COALESCE($2, users.username)
        """
        await db_execute(query, user_id, username)
    except Exception as e:
        logger.error(f"更新用户活动失败 (ID: {user_id}): {e}")

async def is_admin(user_id: int) -> bool:
    """检查用户是否为管理员"""
    try:
        return await db_fetchval("SELECT is_admin FROM users WHERE id = $1", user_id) or False
    except Exception as e:
        logger.error(f"检查用户管理员状态时出错 (ID: {user_id}): {e}")
        return False

async def get_user_name(user_id: int) -> str:
    """获取用户名，如果不存在则返回 ID 字符串"""
    try:
        username = await db_fetchval("SELECT username FROM users WHERE id = $1", user_id)
        return username or f"用户{user_id}"
    except Exception as e:
        logger.error(f"获取用户名称失败 (ID: {user_id}): {e}")
        return f"用户{user_id}"

async def get_user_by_username(username: str):
    """通过用户名获取用户信息"""
    try:
        return await db_fetchrow("SELECT * FROM users WHERE username = $1", username)
    except Exception as e:
        logger.error(f"通过用户名获取用户失败 (Username: {username}): {e}")
        return None

async def get_tags_by_type(tag_type: str) -> List[Dict]:
    """获取特定类型的所有标签"""
    try:
        tags = await db_fetch("SELECT * FROM tags WHERE tag_type = $1 ORDER BY id", tag_type)
        return [dict(tag) for tag in tags]
    except Exception as e:
        logger.error(f"获取标签失败 (类型: {tag_type}): {e}")
        return []

async def get_all_tags() -> Dict[str, List[Dict]]:
    """获取所有标签，按类型分组"""
    try:
        tags = await db_fetch("SELECT * FROM tags ORDER BY tag_type, id")
        result = {"recommend": [], "block": []}
        for tag in tags:
            tag_dict = dict(tag)
            result[tag['tag_type']].append(tag_dict)
        return result
    except Exception as e:
        logger.error(f"获取所有标签失败: {e}")
        return {"recommend": [], "block": []}

async def get_tag_by_id(tag_id: int):
    """通过ID获取标签"""
    try:
        return await db_fetchrow("SELECT * FROM tags WHERE id = $1", tag_id)
    except Exception as e:
        logger.error(f"获取标签失败 (ID: {tag_id}): {e}")
        return None

async def add_tag(tag_type: str, content: str, created_by: int) -> int:
    """添加新标签并返回其ID"""
    try:
        return await db_fetchval(
            "INSERT INTO tags (tag_type, content, created_by) VALUES ($1, $2, $3) RETURNING id",
            tag_type, content, created_by
        )
    except Exception as e:
        logger.error(f"添加标签失败 (内容: {content}): {e}")
        raise

async def add_tags_batch(tag_type: str, contents: List[str], created_by: int) -> List[int]:
    """批量添加标签并返回ID列表"""
    tag_ids = []
    async with db_transaction() as conn:
        for content in contents:
            content = content.strip()
            if content:  # 跳过空字符串
                try:
                    tag_id = await conn.fetchval(
                        "INSERT INTO tags (tag_type, content, created_by) VALUES ($1, $2, $3) RETURNING id",
                        tag_type, content, created_by
                    )
                    tag_ids.append(tag_id)
                except Exception as e:
                    logger.error(f"批量添加标签时单个标签失败 (内容: {content}): {e}")
    return tag_ids

async def remove_tag(tag_id: int):
    """删除标签及其相关联的提名"""
    async with db_transaction() as conn:
        # 先删除引用此标签的提名
        await conn.execute("DELETE FROM nominations WHERE tag_id = $1", tag_id)
        # 然后删除标签本身
        await conn.execute("DELETE FROM tags WHERE id = $1", tag_id)

async def add_nomination(user_id: int, nominee_id: int, tag_id: int) -> bool:
    """添加新的提名，返回是否成功"""
    try:
        query = """
            INSERT INTO nominations (user_id, nominee_id, tag_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, nominee_id, tag_id) DO NOTHING
        """
        result = await db_execute(query, user_id, nominee_id, tag_id)
        return "INSERT" in result
    except Exception as e:
        logger.error(f"添加提名失败 (用户: {user_id}, 被提名人: {nominee_id}, 标签: {tag_id}): {e}")
        return False

async def get_user_nominations(user_id: int, nominee_id: int) -> List:
    """获取用户对特定人的所有提名"""
    try:
        query = """
            SELECT n.id, t.content, t.tag_type, n.created_at
            FROM nominations n
            JOIN tags t ON n.tag_id = t.id
            WHERE n.user_id = $1 AND n.nominee_id = $2
        """
        return await db_fetch(query, user_id, nominee_id)
    except Exception as e:
        logger.error(f"获取用户提名失败 (用户: {user_id}, 被提名人: {nominee_id}): {e}")
        return []

async def get_reputation_summary(nominee_id: int) -> Dict:
    """获取用户声誉总结"""
    try:
        # 获取积极和消极提名的总数
        positive_count = await db_fetchval("""
            SELECT COUNT(*) FROM nominations n
            JOIN tags t ON n.tag_id = t.id
            WHERE n.nominee_id = $1 AND t.tag_type = 'recommend'
        """, nominee_id)
        
        negative_count = await db_fetchval("""
            SELECT COUNT(*) FROM nominations n
            JOIN tags t ON n.tag_id = t.id
            WHERE n.nominee_id = $1 AND t.tag_type = 'block'
        """, nominee_id)
        
        # 获取提名人数
        voter_count = await db_fetchval("""
            SELECT COUNT(DISTINCT user_id) FROM nominations
            WHERE nominee_id = $1
        """, nominee_id)
        
        # 获取最常用的标签
        top_tags = await db_fetch("""
            SELECT t.id, t.content, t.tag_type, COUNT(*) as count
            FROM nominations n
            JOIN tags t ON n.tag_id = t.id
            WHERE n.nominee_id = $1
            GROUP BY t.id, t.content, t.tag_type
            ORDER BY count DESC, t.content
            LIMIT 5
        """, nominee_id)
        
        return {
            "positive_count": positive_count,
            "negative_count": negative_count,
            "voter_count": voter_count,
            "top_tags": [dict(tag) for tag in top_tags]
        }
    except Exception as e:
        logger.error(f"获取声誉总结失败 (ID: {nominee_id}): {e}")
        return {
            "positive_count": 0,
            "negative_count": 0,
            "voter_count": 0,
            "top_tags": []
        }

async def get_reputation_details(nominee_id: int) -> Dict:
    """获取用户声誉详情，包括所有标签及其提名次数"""
    try:
        # 获取所有标签及其提名次数
        tags = await db_fetch("""
            SELECT t.id, t.content, t.tag_type, COUNT(*) as count
            FROM nominations n
            JOIN tags t ON n.tag_id = t.id
            WHERE n.nominee_id = $1
            GROUP BY t.id, t.content, t.tag_type
            ORDER BY count DESC, t.content
        """, nominee_id)
        
        # 按标签类型分组
        recommend_tags = [dict(tag) for tag in tags if tag['tag_type'] == 'recommend']
        block_tags = [dict(tag) for tag in tags if tag['tag_type'] == 'block']
        
        return {
            "recommend_tags": recommend_tags,
            "block_tags": block_tags
        }
    except Exception as e:
        logger.error(f"获取声誉详情失败 (ID: {nominee_id}): {e}")
        return {"recommend_tags": [], "block_tags": []}

async def get_reputation_voters(nominee_id: int, tag_id: int) -> List[Dict]:
    """获取对特定标签投票的用户列表"""
    try:
        query = """
            SELECT u.id, u.username, n.created_at
            FROM nominations n
            JOIN users u ON n.user_id = u.id
            WHERE n.nominee_id = $1 AND n.tag_id = $2
            ORDER BY n.created_at DESC
        """
        voters = await db_fetch(query, nominee_id, tag_id)
        return [dict(voter) for voter in voters]
    except Exception as e:
        logger.error(f"获取投票者列表失败 (被提名人: {nominee_id}, 标签: {tag_id}): {e}")
        return []

async def toggle_favorite(user_id: int, nominee_id: int) -> bool:
    """切换收藏状态，如果添加返回True，如果删除返回False"""
    try:
        # 检查是否已收藏
        exists = await db_fetchval(
            "SELECT EXISTS(SELECT 1 FROM user_favorites WHERE user_id = $1 AND nominee_id = $2)",
            user_id, nominee_id
        )
        
        if exists:
            # 删除收藏
            await db_execute(
                "DELETE FROM user_favorites WHERE user_id = $1 AND nominee_id = $2",
                user_id, nominee_id
            )
            return False
        else:
            # 添加收藏
            await db_execute(
                "INSERT INTO user_favorites (user_id, nominee_id) VALUES ($1, $2)",
                user_id, nominee_id
            )
            return True
    except Exception as e:
        logger.error(f"切换收藏状态失败 (用户: {user_id}, 被收藏人: {nominee_id}): {e}")
        return False

async def get_favorites(user_id: int) -> List[Dict]:
    """获取用户收藏的所有用户"""
    try:
        query = """
            SELECT u.id, u.username, f.added_at,
                  (SELECT COUNT(*) FROM nominations n JOIN tags t ON n.tag_id = t.id 
                   WHERE n.nominee_id = u.id AND t.tag_type = 'recommend') as positive_count,
                  (SELECT COUNT(*) FROM nominations n JOIN tags t ON n.tag_id = t.id 
                   WHERE n.nominee_id = u.id AND t.tag_type = 'block') as negative_count
            FROM user_favorites f
            JOIN users u ON f.nominee_id = u.id
            WHERE f.user_id = $1
            ORDER BY f.added_at DESC
        """
        favorites = await db_fetch(query, user_id)
        return [dict(fav) for fav in favorites]
    except Exception as e:
        logger.error(f"获取用户收藏列表失败 (用户: {user_id}): {e}")
        return []

async def is_favorite(user_id: int, nominee_id: int) -> bool:
    """检查是否已收藏"""
    try:
        return await db_fetchval(
            "SELECT EXISTS(SELECT 1 FROM user_favorites WHERE user_id = $1 AND nominee_id = $2)",
            user_id, nominee_id
        ) or False
    except Exception as e:
        logger.error(f"检查收藏状态失败 (用户: {user_id}, 被收藏人: {nominee_id}): {e}")
        return False

async def get_leaderboard(tag_type: str, limit: int = 10, offset: int = 0, user_id: int = None) -> List[Dict]:
    """
    获取排行榜
    tag_type: 'recommend' 或 'block'
    limit: 返回结果数量
    offset: 从结果的第几条开始返回
    user_id: 如果提供，则返回该用户的排名信息
    """
    try:
        # 基本查询 - 统计每个用户的特定类型标签的提名次数
        query = """
            WITH rankings AS (
                SELECT 
                    u.id, 
                    u.username, 
                    COUNT(*) as nomination_count,
                    ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC, u.username) as rank
                FROM nominations n
                JOIN users u ON n.nominee_id = u.id
                JOIN tags t ON n.tag_id = t.id
                WHERE t.tag_type = $1
                GROUP BY u.id, u.username
            )
        """
        
        # 如果指定了用户ID，获取该用户的排名及其附近的用户
        if user_id:
            query += """
                SELECT 
                    r.id, 
                    r.username, 
                    r.nomination_count, 
                    r.rank,
                    (r.id = $4) as is_current_user
                FROM rankings r
                WHERE 
                    r.id = $4 OR 
                    (r.rank BETWEEN (SELECT rank FROM rankings WHERE id = $4) - 3 
                                 AND (SELECT rank FROM rankings WHERE id = $4) + 3)
                ORDER BY r.rank
            """
            return await db_fetch(query, tag_type, limit, offset, user_id)
        else:
            # 否则按照排名获取前N个用户
            query += """
                SELECT id, username, nomination_count, rank, false as is_current_user
                FROM rankings
                ORDER BY rank
                LIMIT $2 OFFSET $3
            """
            return await db_fetch(query, tag_type, limit, offset)
    except Exception as e:
        logger.error(f"获取排行榜失败 (标签类型: {tag_type}): {e}")
        return []

async def get_system_stats() -> Dict:
    """获取系统统计信息"""
    try:
        stats = {}
        
        # 用户总数
        stats["total_users"] = await db_fetchval("SELECT COUNT(*) FROM users")
        
        # 提名总数
        stats["total_nominations"] = await db_fetchval("SELECT COUNT(*) FROM nominations")
        
        # 标签总数
        stats["total_tags"] = await db_fetchval("SELECT COUNT(*) FROM tags")
        
        # 按类型分组的标签数量
        tag_counts = await db_fetch("SELECT tag_type, COUNT(*) as count FROM tags GROUP BY tag_type")
        for row in tag_counts:
            stats[f"{row['tag_type']}_tags"] = row["count"]
        
        # 最近一周活跃用户
        stats["active_users_last_week"] = await db_fetchval(
            "SELECT COUNT(*) FROM users WHERE last_active > NOW() - INTERVAL '7 days'"
        )
        
        # 最近一周提名
        stats["nominations_last_week"] = await db_fetchval(
            "SELECT COUNT(*) FROM nominations WHERE created_at > NOW() - INTERVAL '7 days'"
        )
        
        return stats
    except Exception as e:
        logger.error(f"获取系统统计失败: {e}")
        return {"error": str(e)}

async def get_all_admins() -> List[Dict]:
    """获取所有管理员"""
    try:
        admins = await db_fetch(
            "SELECT id, username, first_seen, last_active FROM users WHERE is_admin = TRUE ORDER BY id"
        )
        return [dict(admin) for admin in admins]
    except Exception as e:
        logger.error(f"获取管理员列表失败: {e}")
        return []

async def add_admin(user_id: int) -> bool:
    """添加管理员"""
    try:
        exists = await db_fetchval("SELECT EXISTS(SELECT 1 FROM users WHERE id = $1)", user_id)
        if not exists:
            await db_execute("INSERT INTO users (id, is_admin) VALUES ($1, TRUE)", user_id)
        else:
            await db_execute("UPDATE users SET is_admin = TRUE WHERE id = $1", user_id)
        return True
    except Exception as e:
        logger.error(f"添加管理员失败 (ID: {user_id}): {e}")
        return False

async def remove_admin(user_id: int) -> bool:
    """移除管理员权限"""
    try:
        await db_execute("UPDATE users SET is_admin = FALSE WHERE id = $1", user_id)
        return True
    except Exception as e:
        logger.error(f"移除管理员失败 (ID: {user_id}): {e}")
        return False

async def set_system_setting(key: str, value: str, updated_by: int) -> bool:
    """设置系统设置"""
    try:
        query = """
            INSERT INTO system_settings (key, value, updated_at, updated_by)
            VALUES ($1, $2, NOW(), $3)
            ON CONFLICT (key) DO UPDATE 
            SET value = $2, updated_at = NOW(), updated_by = $3
        """
        await db_execute(query, key, value, updated_by)
        return True
    except Exception as e:
        logger.error(f"设置系统设置失败 (键: {key}): {e}")
        return False

async def get_system_setting(key: str) -> Optional[str]:
    """获取系统设置"""
    try:
        return await db_fetchval("SELECT value FROM system_settings WHERE key = $1", key)
    except Exception as e:
        logger.error(f"获取系统设置失败 (键: {key}): {e}")
        return None

async def get_all_system_settings() -> Dict[str, str]:
    """获取所有系统设置"""
    try:
        settings = await db_fetch("SELECT key, value FROM system_settings")
        return {row['key']: row['value'] for row in settings}
    except Exception as e:
        logger.error(f"获取所有系统设置失败: {e}")
        return {}

async def remove_from_leaderboard(user_id: int) -> bool:
    """从排行榜中移除用户（删除所有关于该用户的提名）"""
    try:
        async with db_transaction() as conn:
            await conn.execute("DELETE FROM nominations WHERE nominee_id = $1", user_id)
            await conn.execute("DELETE FROM user_favorites WHERE nominee_id = $1", user_id)
        return True
    except Exception as e:
        logger.error(f"从排行榜移除用户失败 (ID: {user_id}): {e}")
        return False
