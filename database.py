import os
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import DictCursor

pool = None

def init_pool():
    global pool
    if pool is None:
        pool = SimpleConnectionPool(1, 20, dsn=os.environ.get("DATABASE_URL"))

def get_conn():
    return pool.getconn()

def put_conn(conn):
    pool.putconn(conn)

def create_tables():
    """创建或更新所有需要的表。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 用户表：存储用户基本信息和声望
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY,
                    username VARCHAR(255),
                    first_name VARCHAR(255),
                    reputation INT DEFAULT 0
                );
            """)

            # 资源表：存储被评价的每一个独特资源
            cur.execute("""
                CREATE TABLE IF NOT EXISTS resources (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT,
                    message_id BIGINT,
                    sharer_id BIGINT,
                    sharer_username VARCHAR(255),
                    content TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'UTC'),
                    UNIQUE(chat_id, message_id)
                );
            """)

            # 反馈表：记录每一次 /hunt 或 /trap
            cur.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id SERIAL PRIMARY KEY,
                    resource_id INT REFERENCES resources(id) ON DELETE CASCADE,
                    marker_id BIGINT, -- 标记人的ID
                    type VARCHAR(50), -- 'hunt' 或 'trap'
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'UTC'),
                    UNIQUE(resource_id, marker_id) -- 每人对每个资源只能标记一次
                );
            """)
            conn.commit()
            print("All tables checked/created successfully.")
    finally:
        put_conn(conn)

def get_user_rank(reputation: int):
    """根据声望值返回用户的头衔。"""
    from constants import PACK_RANKS
    for threshold, rank in reversed(PACK_RANKS):
        if reputation >= threshold:
            return rank
    return PACK_RANKS[0][1]
