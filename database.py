import os
import asyncpg
import logging
from contextlib import asynccontextmanager
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None
VALID_USERNAME_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789_"

def normalize_username(raw: str) -> Optional[str]:
    if not raw:
        return None
    u = raw.strip().lstrip('@')
    u_lower = u.lower()
    if not u_lower:
        return None
    for ch in u_lower:
        if ch not in VALID_USERNAME_CHARS:
            return None
    if len(u_lower) < 2:
        return None
    return u_lower

async def _create_pool(force: bool = False):
    global _pool
    if _pool and not force:
        return
    if _pool and force:
        try:
            await _pool.close()
        except Exception:
            pass
        _pool = None

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        user = os.getenv("DB_USER")
        pwd = os.getenv("DB_PASSWORD")
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "5432")
        name = os.getenv("DB_NAME")
        dsn = f"postgresql://{user}:{pwd}@{host}:{port}/{name}?sslmode=require"

    min_size = int(os.getenv("DB_POOL_MIN", "0"))
    max_size = int(os.getenv("DB_POOL_MAX", "8"))
    statement_cache_size = int(os.getenv("DB_STATEMENT_CACHE_SIZE", "100"))

    logger.info(f"Creating asyncpg pool (min={min_size} max={max_size})...")
    _pool = await asyncpg.create_pool(
        dsn,
        min_size=min_size,
        max_size=max_size,
        max_inactive_connection_lifetime=300,
        statement_cache_size=statement_cache_size
    )
    logger.info("Database pool created.")

async def init_db():
    await _create_pool()

async def close_db():
    global _pool
    if _pool:
        try:
            await _pool.close()
        finally:
            _pool = None
            logger.info("Database pool closed")

@asynccontextmanager
async def get_conn(retry: bool = True):
    global _pool
    if _pool is None:
        await _create_pool()
    try:
        async with _pool.acquire() as conn:
            yield conn
    except (asyncpg.InterfaceError, asyncpg.PostgresConnectionError) as e:
        if retry:
            logger.warning(f"Connection lost: {e}, recreating pool once...")
            await _create_pool(force=True)
            async with _pool.acquire() as conn2:
                yield conn2
        else:
            raise

# 用户
async def save_user(tg_user) -> None:
    uname = normalize_username(tg_user.username) if tg_user.username else None
    async with get_conn() as conn:
        try:
            await conn.execute(
                """
                INSERT INTO users (user_id, username, first_name, last_name, is_bot, is_hidden, is_virtual, last_active)
                VALUES ($1,$2,$3,$4,$5,false,false,NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    username=COALESCE($2,users.username),
                    first_name=COALESCE($3,users.first_name),
                    last_name=COALESCE($4,users.last_name),
                    last_active=NOW(),
                    is_virtual=false
                """,
                tg_user.id, uname, tg_user.first_name, tg_user.last_name, tg_user.is_bot
            )
        except Exception as e:
            logger.error(f"save_user error: {e}")

async def promote_virtual_user(real_tg_user):
    uname = normalize_username(real_tg_user.username) if real_tg_user.username else None
    if not uname:
        await save_user(real_tg_user)
        return
    async with get_conn() as conn:
        async with conn.transaction():
            virtual_row = await conn.fetchrow(
                "SELECT user_id FROM users WHERE username=$1 AND is_virtual=true",
                uname
            )
            # 保存真实
            await conn.execute(
                """
                INSERT INTO users (user_id, username, first_name, last_name, is_bot, is_hidden, is_virtual, last_active)
                VALUES ($1,$2,$3,$4,$5,false,false,NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    username=COALESCE($2,users.username),
                    first_name=COALESCE($3,users.first_name),
                    last_name=COALESCE($4,users.last_name),
                    last_active=NOW(),
                    is_virtual=false
                """,
                real_tg_user.id, uname, real_tg_user.first_name, real_tg_user.last_name, real_tg_user.is_bot
            )
            if not virtual_row:
                return
            old_id = virtual_row["user_id"]
            new_id = real_tg_user.id
            # ratings
            await conn.execute("UPDATE ratings SET user_id=$1 WHERE user_id=$2", new_id, old_id)
            await conn.execute("UPDATE ratings SET rater_id=$1 WHERE rater_id=$2", new_id, old_id)
            # 处理 favorites 冲突
            await conn.execute("""
                DELETE FROM favorites f
                WHERE f.user_id=$1 AND EXISTS (
                  SELECT 1 FROM favorites ff WHERE ff.user_id=$2 AND ff.favorite_user_id=f.favorite_user_id
                )
            """, old_id, new_id)
            await conn.execute("""
                DELETE FROM favorites f
                WHERE f.favorite_user_id=$1 AND EXISTS (
                  SELECT 1 FROM favorites ff WHERE ff.favorite_user_id=$2 AND ff.user_id=f.user_id
                )
            """, old_id, new_id)
            await conn.execute("UPDATE favorites SET user_id=$1 WHERE user_id=$2", new_id, old_id)
            await conn.execute("UPDATE favorites SET favorite_user_id=$1 WHERE favorite_user_id=$2", new_id, old_id)
            # queries
            await conn.execute("UPDATE user_queries SET requester_id=$1 WHERE requester_id=$2", new_id, old_id)
            await conn.execute("UPDATE user_queries SET target_user_id=$1 WHERE target_user_id=$2", new_id, old_id)
            # 删除虚拟
            await conn.execute("DELETE FROM users WHERE user_id=$1", old_id)

async def get_or_create_virtual_user(username: str) -> Optional[Dict[str,Any]]:
    uname = normalize_username(username)
    if not uname:
        return None
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, username, first_name, last_name, is_virtual, is_hidden FROM users WHERE username=$1",
            uname
        )
        if row:
            return dict(row)
        vid = await conn.fetchval("SELECT nextval('virtual_user_seq')")
        vid = -int(vid)
        inserted = await conn.fetchrow(
            """
            INSERT INTO users (user_id, username, first_name, last_name, is_bot, is_hidden, is_virtual, created_at, last_active)
            VALUES ($1,$2,'','',false,false,true,NOW(),NOW())
            RETURNING user_id, username, first_name, last_name, is_virtual, is_hidden
            """,
            vid, uname
        )
        return dict(inserted)

async def get_user_info(user_id: int) -> Optional[Dict[str,Any]]:
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, username, first_name, last_name, is_virtual, is_hidden FROM users WHERE user_id=$1",
            user_id
        )
        return dict(row) if row else None

async def log_user_query(requester_id: int, target_user_id: int, chat_id: Optional[int]):
    async with get_conn() as conn:
        try:
            await conn.execute(
                "INSERT INTO user_queries (requester_id, target_user_id, chat_id) VALUES ($1,$2,$3)",
                requester_id, target_user_id, chat_id
            )
        except Exception as e:
            logger.error(f"log_user_query error: {e}")

# 标签
async def get_tags_by_type(sentiment: str) -> List[Dict[str,Any]]:
    t = 'positive' if sentiment == 'positive' else 'negative'
    async with get_conn() as conn:
        rows = await conn.fetch(
            "SELECT id, name, type, is_active FROM tags WHERE type=$1 AND is_active=true ORDER BY id ASC",
            t
        )
        return [dict(r) for r in rows]

# 评价（终身唯一）
async def get_or_create_pair_rating(rater_id: int, user_id: int, sentiment: str):
    assert sentiment in ("positive","negative")
    async with get_conn() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT id, sentiment FROM ratings WHERE rater_id=$1 AND user_id=$2 FOR UPDATE",
                rater_id, user_id
            )
            if row:
                rid = row["id"]
                old_s = row["sentiment"]
                if old_s != sentiment:
                    await conn.execute("UPDATE ratings SET sentiment=$1 WHERE id=$2", sentiment, rid)
                    return rid, False, sentiment, True
                return rid, False, old_s, False
            new_row = await conn.fetchrow(
                """
                INSERT INTO ratings (user_id, rater_id, sentiment)
                VALUES ($1,$2,$3)
                RETURNING id, sentiment
                """,
                user_id, rater_id, sentiment
            )
            return new_row["id"], True, new_row["sentiment"], True

async def attach_tags_to_rating(rating_id: int, tag_ids: List[int]) -> None:
    if not tag_ids:
        return
    async with get_conn() as conn:
        async with conn.transaction():
            exist = await conn.fetch("SELECT tag_id FROM rating_tags WHERE rating_id=$1", rating_id)
            have = {r['tag_id'] for r in exist}
            new_ids = [t for t in tag_ids if t not in have]
            for tid in new_ids:
                await conn.execute("INSERT INTO rating_tags (rating_id, tag_id) VALUES ($1,$2)", rating_id, tid)

async def clear_tags_if_sentiment_changed(rating_id: int):
    async with get_conn() as conn:
        await conn.execute("DELETE FROM rating_tags WHERE rating_id=$1", rating_id)

# 收藏
async def is_user_favorite(user_id: int, target_user_id: int) -> bool:
    async with get_conn() as conn:
        v = await conn.fetchval(
            "SELECT 1 FROM favorites WHERE user_id=$1 AND favorite_user_id=$2",
            user_id, target_user_id
        )
        return v is not None

async def add_favorite(user_id: int, target_user_id: int) -> bool:
    async with get_conn() as conn:
        try:
            await conn.execute(
                """
                INSERT INTO favorites (user_id, favorite_user_id)
                VALUES ($1,$2) ON CONFLICT DO NOTHING
                """,
                user_id, target_user_id
            )
            return True
        except Exception as e:
            logger.error(f"add_favorite error: {e}")
            return False

async def remove_favorite(user_id: int, target_user_id: int) -> bool:
    async with get_conn() as conn:
        try:
            res = await conn.execute(
                "DELETE FROM favorites WHERE user_id=$1 AND favorite_user_id=$2",
                user_id, target_user_id
            )
            return res.endswith("1")
        except Exception as e:
            logger.error(f"remove_favorite error: {e}")
            return False

async def get_user_favorites(user_id: int) -> List[Dict[str,Any]]:
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT f.favorite_user_id,
                   u.username,
                   u.first_name,
                   u.last_name,
                   f.created_at,
                   COALESCE(
                     (SELECT COUNT(*) FROM ratings r WHERE r.user_id=f.favorite_user_id AND r.sentiment='positive'),
                     0
                   ) -
                   COALESCE(
                     (SELECT COUNT(*) FROM ratings r WHERE r.user_id=f.favorite_user_id AND r.sentiment='negative'),
                     0
                   ) AS reputation_score
            FROM favorites f
            JOIN users u ON f.favorite_user_id = u.user_id
            WHERE f.user_id=$1 AND NOT u.is_hidden
            ORDER BY f.created_at DESC
            """,
            user_id
        )
        return [dict(r) for r in rows]

# 用户声誉
async def get_user_reputation(user_id: int) -> Dict[str,Any]:
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE sentiment='positive') AS recommendations,
                COUNT(*) FILTER (WHERE sentiment='negative') AS warnings
            FROM ratings
            WHERE user_id=$1
            """,
            user_id
        )
        rec = row["recommendations"] or 0
        warn = row["warnings"] or 0
        score = rec - warn
        tags = await conn.fetch(
            """
            SELECT t.name, COUNT(*) as count
            FROM ratings r
            JOIN rating_tags rt ON r.id=rt.rating_id
            JOIN tags t ON rt.tag_id=t.id
            WHERE r.user_id=$1
            GROUP BY t.name
            ORDER BY count DESC
            LIMIT 10
            """,
            user_id
        )
        return {
            "recommendations": rec,
            "warnings": warn,
            "score": score,
            "tags": [dict(t) for t in tags]
        }

async def get_detailed_user_stats(user_id: int) -> Dict[str,Any]:
    async with get_conn() as conn:
        pos = await conn.fetch(
            """
            SELECT t.name, COUNT(*) as count
            FROM ratings r
            JOIN rating_tags rt ON r.id=rt.rating_id
            JOIN tags t ON t.id=rt.tag_id
            WHERE r.user_id=$1 AND r.sentiment='positive'
            GROUP BY t.name
            ORDER BY count DESC
            LIMIT 10
            """,
            user_id
        )
        neg = await conn.fetch(
            """
            SELECT t.name, COUNT(*) as count
            FROM ratings r
            JOIN rating_tags rt ON r.id=rt.rating_id
            JOIN tags t ON t.id=rt.tag_id
            WHERE r.user_id=$1 AND r.sentiment='negative'
            GROUP BY t.name
            ORDER BY count DESC
            LIMIT 10
            """,
            user_id
        )
        recent = await conn.fetch(
            """
            SELECT r.sentiment, t.name AS tag_name, r.created_at
            FROM ratings r
            LEFT JOIN rating_tags rt ON r.id=rt.rating_id
            LEFT JOIN tags t ON rt.tag_id=t.id
            WHERE r.user_id=$1
            ORDER BY r.created_at DESC
            LIMIT 12
            """,
            user_id
        )
        return {
            "positive_tags": [dict(x) for x in pos],
            "negative_tags": [dict(x) for x in neg],
            "recent_ratings": [dict(x) for x in recent]
        }

# 排行榜分页（不区分虚拟）
async def get_leaderboard_page(page: int, page_size: int) -> Tuple[List[Dict[str,Any]], int]:
    offset = (page - 1) * page_size
    async with get_conn() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM users u WHERE NOT u.is_hidden")
        rows = await conn.fetch(
            """
            SELECT u.user_id, u.username, u.first_name, u.last_name,
                   COALESCE(p.cnt,0) AS recommendations,
                   COALESCE(n.cnt,0) AS warnings,
                   COALESCE(p.cnt,0) - COALESCE(n.cnt,0) AS reputation_score
            FROM users u
            LEFT JOIN (
                SELECT user_id, COUNT(*) cnt FROM ratings WHERE sentiment='positive' GROUP BY user_id
            ) p ON p.user_id = u.user_id
            LEFT JOIN (
                SELECT user_id, COUNT(*) cnt FROM ratings WHERE sentiment='negative' GROUP BY user_id
            ) n ON n.user_id = u.user_id
            WHERE NOT u.is_hidden
            ORDER BY reputation_score DESC, u.user_id ASC
            LIMIT $1 OFFSET $2
            """,
            page_size, offset
        )
        return [dict(r) for r in rows], total

async def get_bot_statistics() -> Dict[str,Any]:
    async with get_conn() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE NOT is_hidden")
        total_ratings = await conn.fetchval("SELECT COUNT(*) FROM ratings")
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        active_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE last_active >= $1", since)
        return {
            "total_users": total_users or 0,
            "total_ratings": total_ratings or 0,
            "active_users_24h": active_users or 0
        }

# 标签管理
async def add_tag(name: str, tag_type: str) -> bool:
    tag_type = 'positive' if tag_type == 'positive' else 'negative'
    async with get_conn() as conn:
        try:
            await conn.execute(
                "INSERT INTO tags (name, type) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                name.strip(), tag_type
            )
            return True
        except Exception as e:
            logger.error(f"add_tag error: {e}")
            return False

async def list_tags() -> List[Dict[str,Any]]:
    async with get_conn() as conn:
        rows = await conn.fetch("SELECT id, name, type, is_active FROM tags ORDER BY id ASC")
        return [dict(r) for r in rows]

async def toggle_tag(tag_id: int) -> bool:
    async with get_conn() as conn:
        try:
            await conn.execute("UPDATE tags SET is_active = NOT is_active WHERE id=$1", tag_id)
            return True
        except Exception as e:
            logger.error(f"toggle_tag error: {e}")
            return False

async def delete_tag(tag_id: int) -> bool:
    async with get_conn() as conn:
        try:
            await conn.execute("DELETE FROM tags WHERE id=$1", tag_id)
            return True
        except Exception as e:
            logger.error(f"delete_tag error: {e}")
            return False

async def set_user_hidden_by_username(username: str, hidden: bool) -> bool:
    uname = normalize_username(username)
    if not uname:
        return False
    async with get_conn() as conn:
        res = await conn.execute("UPDATE users SET is_hidden=$1 WHERE username=$2", hidden, uname)
        return res.endswith("1")
