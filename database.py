import asyncpg
import logging
import os
from dotenv import load_dotenv

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Connection Pool ---
_pool = None

async def get_pool():
    """
    Returns the existing database connection pool or creates a new one
    using the DATABASE_URL environment variable.
    """
    global _pool
    if _pool is None:
        # Load environment variables, but do not override existing system variables.
        # This ensures that variables set in the Render UI take precedence.
        load_dotenv(override=False)
        
        DATABASE_URL = os.getenv("DATABASE_URL")
        if not DATABASE_URL:
            logger.critical("DATABASE_URL not found in environment variables. Cannot connect to the database.")
            raise ValueError("DATABASE_URL is not set.")

        try:
            # Use the DSN (Data Source Name) which is the DATABASE_URL.
            _pool = await asyncpg.create_pool(
                dsn=DATABASE_URL,
                min_size=1,
                max_size=10,
                max_queries=50,
                max_inactive_connection_lifetime=300
            )
            logger.info("Database connection pool created successfully.")
        except Exception as e:
            logger.critical(f"Failed to create database connection pool: {e}", exc_info=True)
            raise
    return _pool

async def close_pool():
    """Closes the database connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed.")

# --- Database Initialization ---
async def init_db():
    """
    Initializes the database: creates tables and adds necessary columns/indexes if they don't exist.
    """
    db_pool = await get_pool()
    async with db_pool.acquire() as connection:
        logger.info("Starting database initialization...")

        # User Table
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                pkid SERIAL PRIMARY KEY,
                id BIGINT UNIQUE NOT NULL,
                username VARCHAR(32),
                first_name VARCHAR(255) NOT NULL,
                is_admin BOOLEAN NOT NULL DEFAULT FALSE,
                is_hidden BOOLEAN NOT NULL DEFAULT FALSE
            );
        """)
        # Add is_hidden column to existing table if missing
        await connection.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_hidden BOOLEAN NOT NULL DEFAULT FALSE;")

        # Tags Table
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                pkid SERIAL PRIMARY KEY,
                name VARCHAR(50) UNIQUE NOT NULL,
                type VARCHAR(10) NOT NULL, -- 'recommend' or 'warn'
                is_active BOOLEAN NOT NULL DEFAULT TRUE
            );
        """)

        # Evaluations Table
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS evaluations (
                pkid SERIAL PRIMARY KEY,
                evaluator_user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                target_user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                tag_pkid INTEGER NOT NULL REFERENCES tags(pkid) ON DELETE CASCADE,
                type VARCHAR(10) NOT NULL, -- 'recommend' or 'warn'
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        # Add created_at column to existing table if missing
        await connection.execute("ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();")

        # Favorites Table
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                pkid SERIAL PRIMARY KEY,
                user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                target_user_pkid INTEGER NOT NULL REFERENCES users(pkid) ON DELETE CASCADE,
                UNIQUE(user_pkid, target_user_pkid)
            );
        """)

        # Menu Buttons Table
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS menu_buttons (
                pkid SERIAL PRIMARY KEY,
                name VARCHAR(50) NOT NULL,
                action_id VARCHAR(50) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                sort_order INTEGER NOT NULL DEFAULT 0
            );
        """)
        
        # --- PERFORMANCE UPGRADE: ADD INDEXES ---
        logger.info("Applying database indexes for performance...")
        await connection.execute("CREATE INDEX IF NOT EXISTS idx_users_id ON users (id);")
        await connection.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users (username);")
        await connection.execute("CREATE INDEX IF NOT EXISTS idx_users_is_hidden ON users (is_hidden);")
        
        await connection.execute("CREATE INDEX IF NOT EXISTS idx_evaluations_target_user ON evaluations (target_user_pkid);")
        await connection.execute("CREATE INDEX IF NOT EXISTS idx_evaluations_evaluator_user ON evaluations (evaluator_user_pkid);")
        await connection.execute("CREATE INDEX IF NOT EXISTS idx_evaluations_type_created_at ON evaluations (type, created_at);")
        
        await connection.execute("CREATE INDEX IF NOT EXISTS idx_favorites_user_target ON favorites (user_pkid, target_user_pkid);")
        await connection.execute("CREATE INDEX IF NOT EXISTS idx_tags_type ON tags (type);")
        await connection.execute("CREATE INDEX IF NOT EXISTS idx_menu_buttons_order ON menu_buttons (sort_order);")

        logger.info("Database initialization and performance upgrade complete.")

# --- Generic DB Helpers ---
async def db_fetch_all(query, *params):
    db_pool = await get_pool()
    async with db_pool.acquire() as connection:
        return await connection.fetch(query, *params)

async def db_fetch_one(query, *params):
    db_pool = await get_pool()
    async with db_pool.acquire() as connection:
        return await connection.fetchrow(query, *params)

async def db_fetch_val(query, *params):
    db_pool = await get_pool()
    async with db_pool.acquire() as connection:
        return await connection.fetchval(query, *params)

async def db_execute(query, *params):
    db_pool = await get_pool()
    async with db_pool.acquire() as connection:
        return await connection.execute(query, *params)

# --- User specific functions ---
async def get_or_create_user(user_data: dict) -> int:
    """
    Gets a user by their Telegram ID, creating them if they don't exist.
    This is the unified and safer function.
    """
    user_id = user_data.id
    # Ensure username is not None, which can happen for users with privacy settings
    username = user_data.username if user_data.username else f"user_{user_id}"
    first_name = user_data.first_name
    
    # Check if user exists
    user_pkid = await db_fetch_val("SELECT pkid FROM users WHERE id = $1", user_id)
    
    if user_pkid:
        # Update user info if they exist
        await db_execute(
            "UPDATE users SET username = $1, first_name = $2 WHERE id = $3",
            username, first_name, user_id
        )
        return user_pkid
    else:
        # Create user if they don't exist
        # Check if this user should be an admin
        admin_user_ids_str = os.getenv("ADMIN_USER_IDS", "")
        admin_user_ids = [admin_id.strip() for admin_id in admin_user_ids_str.split(',') if admin_id.strip()]
        is_admin = str(user_id) in admin_user_ids

        return await db_fetch_val(
            "INSERT INTO users (id, username, first_name, is_admin) VALUES ($1, $2, $3, $4) RETURNING pkid",
            user_id, username, first_name, is_admin
        )
