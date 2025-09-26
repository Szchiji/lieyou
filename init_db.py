import asyncio
import asyncpg
import os

DATABASE_URL = os.environ.get("DATABASE_URL")

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS members (
    user_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    region TEXT,
    name TEXT,
    name_link TEXT,
    channel TEXT,
    channel_link TEXT,
    bust TEXT,
    price1 TEXT,
    price2 TEXT,
    expire_date DATE,
    checkins TEXT[],  -- PostgreSQL数组类型
    PRIMARY KEY (user_id, chat_id)
);
"""

async def main():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(CREATE_TABLE_SQL)
    await conn.close()
    print("Tables created successfully.")

if __name__ == "__main__":
    asyncio.run(main())
