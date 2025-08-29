import psycopg2
import psycopg2.extras
from psycopg2 import pool
from contextlib import contextmanager
from os import environ
import logging

logger = logging.getLogger(__name__)
db_pool = None

def init_pool():
    """初始化数据库连接池。"""
    global db_pool
    try:
        # --- 核心改动：直接使用 Render 提供的 DATABASE_URL ---
        database_url = environ.get("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL 环境变量未设置。机器人无法连接到数据库。")

        db_pool = pool.SimpleConnectionPool(
            1, 20,
            dsn=database_url  # 使用 DATABASE_URL 作为唯一的数据源名称
        )
        logger.info("数据库连接池初始化成功。")
    except Exception as e:
        logger.critical(f"数据库连接失败: {e}")
        raise

@contextmanager
def db_cursor():
    """提供一个数据库游标的上下文管理器。"""
    if not db_pool:
        raise ConnectionError("数据库连接池未初始化。")
    conn = db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            yield cur
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        db_pool.putconn(conn)

def create_tables():
    """检查并创建所有需要的表。"""
    # (此函数内容是正确的，保持不变)
    commands = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            username VARCHAR(255),
            first_name VARCHAR(255),
            is_admin BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc')
        )
        """,
        """
        ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE;
        """,
        """
        CREATE TABLE IF NOT EXISTS targets (
            id BIGINT PRIMARY KEY,
            username VARCHAR(255),
            first_name VARCHAR(255),
            upvotes INT DEFAULT 0,
            downvotes INT DEFAULT 0,
            first_reporter_id BIGINT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc')
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS votes (
            voter_id BIGINT,
            target_id BIGINT,
            vote_type INT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc'),
            PRIMARY KEY (voter_id, target_id),
            FOREIGN KEY (voter_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (target_id) REFERENCES targets(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS tags (
            id SERIAL PRIMARY KEY,
            tag_text VARCHAR(255) UNIQUE,
            tag_type INT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS applied_tags (
            id SERIAL PRIMARY KEY,
            vote_voter_id BIGINT,
            vote_target_id BIGINT,
            tag_id INT,
            FOREIGN KEY (vote_voter_id, vote_target_id) REFERENCES votes(voter_id, target_id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS favorites (
            user_id BIGINT,
            target_id BIGINT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc'),
            PRIMARY KEY (user_id, target_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (target_id) REFERENCES targets(id) ON DELETE CASCADE
        )
        """
    ]
    
    with db_cursor() as cur:
        for command in commands:
            cur.execute(command)

        cur.execute("SELECT COUNT(*) FROM tags")
        if cur.fetchone()[0] == 0:
            logger.info("数据库中没有标签，正在插入默认标签...")
            default_tags = {
                1: ["技术大佬", "交易爽快", "乐于助人", "信誉良好"],
                -1: ["骗子", "态度恶劣", "鸽子王", "垃圾信息"]
            }
            for tag_type, tags in default_tags.items():
                for tag in tags:
                    cur.execute("INSERT INTO tags (tag_text, tag_type) VALUES (%s, %s) ON CONFLICT (tag_text) DO NOTHING", (tag, tag_type))
            logger.info("默认标签已插入。")

    logger.info("所有表都已成功检查/创建。")
