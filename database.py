import psycopg2
import psycopg2.pool
from os import environ
import logging

# 全局变量，用于存储连接池
pool = None
logger = logging.getLogger(__name__)

def init_pool():
    """初始化数据库连接池。"""
    global pool
    if pool is None:
        try:
            pool = psycopg2.pool.SimpleConnectionPool(
                1, 20, dsn=environ.get("DATABASE_URL")
            )
            logger.info("数据库连接池初始化成功。")
        except psycopg2.OperationalError as e:
            logger.error(f"数据库连接失败: {e}")
            raise

def get_db_connection():
    """从连接池获取一个数据库连接。"""
    if pool is None:
        raise Exception("数据库连接池未初始化。")
    return pool.getconn()

def put_db_connection(conn):
    """将数据库连接放回连接池。"""
    if pool is not None:
        pool.putconn(conn)

class get_db_cursor:
    """上下文管理器，用于获取和释放数据库游标。"""
    def __enter__(self):
        self.conn = get_db_connection()
        self.cursor = self.conn.cursor()
        return self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val is not None:
            self.conn.rollback()
        else:
            self.conn.commit()
        self.cursor.close()
        put_db_connection(self.conn)

def create_tables():
    """创建数据库表（如果它们不存在）。"""
    commands = (
        """
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            username VARCHAR(255),
            first_name VARCHAR(255),  -- <-- 这是新增的列
            reputation INT DEFAULT 0 NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS prey (
            id SERIAL PRIMARY KEY,
            owner_id BIGINT REFERENCES users(id),
            name VARCHAR(255) NOT NULL,
            trapped_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            is_hunted BOOLEAN DEFAULT FALSE,
            hunted_at TIMESTAMP WITH TIME ZONE
        )
        """
    )
    try:
        with get_db_cursor() as cur:
            for command in commands:
                cur.execute(command)
        logger.info("所有表都已成功检查/创建。")
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"创建表时出错: {error}")
