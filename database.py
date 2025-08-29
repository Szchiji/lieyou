import psycopg2
import psycopg2.extras
import psycopg2.pool
from os import environ
import logging

logger = logging.getLogger(__name__)
db_pool = None

def init_pool():
    """初始化数据库连接池。"""
    global db_pool
    if db_pool is None:
        try:
            db_pool = psycopg2.pool.SimpleConnectionPool(
                1, 20, dsn=environ.get("DATABASE_URL")
            )
            logger.info("数据库连接池初始化成功。")
        except psycopg2.OperationalError as e:
            logger.critical(f"数据库连接失败: {e}")
            raise

def get_db_cursor():
    """从连接池获取一个数据库连接和游标。"""
    if db_pool is None:
        raise Exception("数据库连接池未初始化。")
    conn = db_pool.getconn()
    conn.autocommit = True
    # 使用 psycopg2.extras.DictCursor 让查询结果可以像字典一样访问
    return conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

def release_db_connection(conn):
    """将连接释放回池中。"""
    if db_pool is not None:
        db_pool.putconn(conn)

class db_cursor:
    """上下文管理器，用于自动获取和释放数据库连接。"""
    def __enter__(self):
        self.conn = db_pool.getconn()
        self.conn.autocommit = True
        self.cursor = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        return self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cursor.close()
        release_db_connection(self.conn)

def create_tables():
    """创建所有需要的数据库表。"""
    commands = (
        """
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            username VARCHAR(255),
            first_name VARCHAR(255),
            is_admin BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        """,
        # 移除了 users 表中的 reputation 字段，因为它应该在 targets 表中
        """
        CREATE TABLE IF NOT EXISTS targets (
            id BIGINT PRIMARY KEY,
            username VARCHAR(255),
            first_name VARCHAR(255),
            upvotes INT DEFAULT 0,
            downvotes INT DEFAULT 0,
            first_reporter_id BIGINT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (first_reporter_id) REFERENCES users (id) ON DELETE SET NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS votes (
            voter_id BIGINT,
            target_id BIGINT,
            vote_type INT, -- 1 for upvote, -1 for downvote
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (voter_id, target_id),
            FOREIGN KEY (voter_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (target_id) REFERENCES targets (id) ON DELETE CASCADE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS favorites (
            user_id BIGINT,
            target_id BIGINT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, target_id),
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (target_id) REFERENCES targets (id) ON DELETE CASCADE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS tags (
            id SERIAL PRIMARY KEY,
            tag_text VARCHAR(100) UNIQUE NOT NULL,
            tag_type INT NOT NULL -- 1 for upvote, -1 for downvote
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS applied_tags (
            id SERIAL PRIMARY KEY,
            vote_voter_id BIGINT,
            vote_target_id BIGINT,
            tag_id INT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vote_voter_id, vote_target_id) REFERENCES votes (voter_id, target_id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags (id) ON DELETE CASCADE
        );
        """
    )
    try:
        with db_cursor() as cur:
            for command in commands:
                cur.execute(command)
            
            # 为系统添加一些默认标签
            cur.execute("SELECT COUNT(*) FROM tags;")
            if cur.fetchone()[0] == 0:
                logger.info("数据库中没有标签，正在插入默认标签...")
                default_tags = [
                    ('交易爽快', 1), ('技术大佬', 1), ('乐于助人', 1), ('信誉商家', 1),
                    ('交易拖延', -1), ('骗子', -1), ('发布广告', -1), ('态度恶劣', -1)
                ]
                for text, type in default_tags:
                    cur.execute("INSERT INTO tags (tag_text, tag_type) VALUES (%s, %s) ON CONFLICT (tag_text) DO NOTHING;", (text, type))
                logger.info("默认标签已插入。")

        logger.info("所有表都已成功检查/创建。")
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"创建表时出错: {error}")
        raise
