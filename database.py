import os
import logging
import asyncpg
from typing import Optional, List, Dict, Any
from telegram import User as TelegramUser

logger = logging.getLogger(__name__)
pool: asyncpg.Pool = None

async def init_db():
    """Initialize the database connection pool and create tables if they don't exist."""
    global pool
    
    # 优先使用 DATABASE_URL，如果没有则使用分离的配置
    database_url = os.getenv('DATABASE_URL')
    
    if database_url:
        # 处理一些云平台的 postgres:// 格式（需要改为 postgresql://）
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        
        pool = await asyncpg.create_pool(
            database_url,
            min_size=1,
            max_size=10,
            ssl='require' if 'sslmode=require' in database_url else None
        )
    else:
        # 使用分离的配置变量
        pool = await asyncpg.create_pool(
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME'),
            host=os.getenv('DB_HOST'),
            port=os.getenv('DB_PORT'),
            min_size=1,
            max_size=10
        )
    
    logger.info("Database pool created successfully.")
    await create_tables()

async def create_tables():
    """Create all necessary tables if they don't exist."""
    async with pool.acquire() as conn:
        # Users table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                pkid SERIAL PRIMARY KEY,
                id BIGINT UNIQUE NOT NULL,
                username VARCHAR(255),
                first_name VARCHAR(255),
                last_name VARCHAR(255),
                is_admin BOOLEAN DEFAULT FALSE,
                is_hidden BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tags table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                pkid SERIAL PRIMARY KEY,
                name VARCHAR(100) UNIQUE NOT NULL,
                type VARCHAR(20) NOT NULL CHECK (type IN ('recommend', 'warn')),
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Evaluations table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS evaluations (
                pkid SERIAL PRIMARY KEY,
                evaluator_user_pkid INTEGER REFERENCES users(pkid),
                target_user_pkid INTEGER REFERENCES users(pkid),
                tag_pkid INTEGER REFERENCES tags(pkid) ON DELETE CASCADE,
                type VARCHAR(20) NOT NULL CHECK (type IN ('recommend', 'warn')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(evaluator_user_pkid, target_user_pkid, tag_pkid)
            )
        """)
        
        # Favorites table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                pkid SERIAL PRIMARY KEY,
                user_pkid INTEGER REFERENCES users(pkid),
                target_user_pkid INTEGER REFERENCES users(pkid),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_pkid, target_user_pkid)
            )
        """)
        
        # Menu buttons table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS menu_buttons (
                pkid SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                action_id VARCHAR(50) NOT NULL,
                sort_order INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes for better performance
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_evaluations_target ON evaluations(target_user_pkid)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_evaluations_evaluator ON evaluations(evaluator_user_pkid)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_favorites_target ON favorites(target_user_pkid)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        
        # Insert default data
        await insert_default_data(conn)
        
        # Create/update admin user
        await create_admin_user(conn)
        
    logger.info("All tables created successfully.")

async def insert_default_data(conn):
    """Insert default tags and menu buttons."""
    # Default tags
    default_tags = [
        ('靠谱', 'recommend'),
        ('热心', 'recommend'),
        ('专业', 'recommend'),
        ('骗子', 'warn'),
        ('失联', 'warn'),
        ('态度差', 'warn'),
    ]
    
    for name, tag_type in default_tags:
        await conn.execute("""
            INSERT INTO tags (name, type) 
            VALUES ($1, $2) 
            ON CONFLICT (name) DO NOTHING
        """, name, tag_type)
    
    # Default menu buttons
    default_buttons = [
        ('📊 查看排行榜', 'show_leaderboard', 1),
        ('❤️ 我的收藏', 'show_my_favorites', 2),
        ('❓ 帮助', 'show_help', 3),
    ]
    
    for name, action_id, sort_order in default_buttons:
        await conn.execute("""
            INSERT INTO menu_buttons (name, action_id, sort_order) 
            VALUES ($1, $2, $3) 
            ON CONFLICT DO NOTHING
        """, name, action_id, sort_order)

async def create_admin_user(conn):
    """Create or update the admin user."""
    admin_id = os.getenv('ADMIN_USER_ID')
    if admin_id:
        await conn.execute("""
            INSERT INTO users (id, is_admin) 
            VALUES ($1, TRUE) 
            ON CONFLICT (id) DO UPDATE 
            SET is_admin = TRUE
        """, int(admin_id))
        logger.info(f"Admin user {admin_id} created/updated.")

# --- User Management ---
async def save_user(user: TelegramUser) -> int:
    """Save or update a Telegram user and return their pkid."""
    async with pool.acquire() as conn:
        pkid = await conn.fetchval("""
            INSERT INTO users (id, username, first_name, last_name) 
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (id) DO UPDATE 
            SET username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                updated_at = CURRENT_TIMESTAMP
            RETURNING pkid
        """, user.id, user.username, user.first_name, user.last_name)
        return pkid

async def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    """Get a user by their Telegram ID."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        return dict(row) if row else None

# --- Generic Database Operations ---
async def db_fetch_one(query: str, *args) -> Optional[Dict[str, Any]]:
    """Fetch one row from the database."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, *args)
        return dict(row) if row else None

async def db_fetch_all(query: str, *args) -> List[Dict[str, Any]]:
    """Fetch all rows from the database."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *args)
        return [dict(row) for row in rows]

async def db_fetch_val(query: str, *args) -> Any:
    """Fetch a single value from the database."""
    async with pool.acquire() as conn:
        return await conn.fetchval(query, *args)

async def db_execute(query: str, *args) -> str:
    """Execute a query without returning results."""
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)

async def close_db():
    """Close the database connection pool."""
    global pool
    if pool:
        await pool.close()
        logger.info("Database pool closed.")
