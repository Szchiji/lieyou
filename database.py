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
pool = None

async def get_pool():
    """Returns the existing database connection pool or creates a new one."""
    global pool
    if pool is None:
        load_dotenv()
        try:
            pool = await asyncpg.create_pool(
                user=os.getenv("DB_USER"),
                password=os.getenv("DB_PASSWORD"),
                database=os.getenv("DB_NAME"),
                host=os.getenv("DB_HOST"),
                port=os.getenv("DB_PORT")
            )
            logger.info("Database connection pool created successfully.")
        except Exception as e:
            logger.critical(f"Failed to create database connection pool: {e}")
            raise
    return pool

async def close_pool():
    """Closes the database connection pool."""
    global pool
    if pool:
        await pool.close()
        pool = None
        logger.info("Database connection pool closed.")

# --- Database Initialization ---
async def init_db():
    """
    Initializes the database: creates tables and adds necessary columns/indexes if they don't exist.
    This is the upgraded version for performance and new features.
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
        await connection.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='is_hidden') THEN
                    ALTER TABLE users ADD COLUMN is_hidden BOOLEAN NOT NULL DEFAULT FALSE;
                END IF;
            END $$;
        """)

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
        await connection.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='evaluations' AND column_name='created_at') THEN
                    ALTER TABLE evaluations ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
                END IF;
            END $$;
        """)

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
async def get_user(user_id: int):
    """Gets a user by their Telegram ID."""
    return await db_fetch_one("SELECT * FROM users WHERE id = $1", user_id)

async def save_user(user: dict):
    """Saves or updates a user in the database."""
    user_id = user.id
    username = user.username
    first_name = user.first_name
    admin_user_id = os.getenv("ADMIN_USER_ID")

    is_admin = str(user_id) == str(admin_user_id)

    existing_user = await get_user(user_id)
    if existing_user:
        await db_execute(
            "UPDATE users SET username = $1, first_name = $2, is_admin = $3 WHERE id = $4",
            username, first_name, is_admin, user_id
        )
        return existing_user['pkid']
    else:
        return await db_fetch_val(
            "INSERT INTO users (id, username, first_name, is_admin) VALUES ($1, $2, $3, $4) RETURNING pkid",
            user_id, username, first_name, is_admin
        )
