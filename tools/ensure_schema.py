import logging
from database import get_conn

logger = logging.getLogger(__name__)

async def ensure_schema():
    """
    启动时自检/自愈数据库结构（兼容旧表），幂等可反复执行。
    """
    sql = """
    -- Users 表修复/创建
    DO $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='users' AND column_name='user_id'
      ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='users' AND column_name='id'
      ) THEN
        ALTER TABLE users RENAME COLUMN id TO user_id;
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='users' AND column_name='user_id'
      ) THEN
        CREATE TABLE IF NOT EXISTS users (
          user_id BIGINT PRIMARY KEY,
          username TEXT UNIQUE,
          first_name TEXT,
          last_name TEXT,
          is_bot BOOLEAN NOT NULL DEFAULT false,
          is_hidden BOOLEAN NOT NULL DEFAULT false,
          is_virtual BOOLEAN NOT NULL DEFAULT false,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          last_active TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
      END IF;

      PERFORM 1
      FROM information_schema.columns
      WHERE table_name='users' AND column_name='user_id' AND data_type='bigint';
      IF NOT FOUND THEN
        ALTER TABLE users ALTER COLUMN user_id TYPE BIGINT USING user_id::bigint;
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        WHERE t.relname='users' AND c.contype='p'
      ) THEN
        ALTER TABLE users ADD PRIMARY KEY (user_id);
      END IF;

      IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='username') THEN
        ALTER TABLE users ADD COLUMN username TEXT;
      END IF;
      IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='first_name') THEN
        ALTER TABLE users ADD COLUMN first_name TEXT;
      END IF;
      IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='last_name') THEN
        ALTER TABLE users ADD COLUMN last_name TEXT;
      END IF;
      IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='is_bot') THEN
        ALTER TABLE users ADD COLUMN is_bot BOOLEAN NOT NULL DEFAULT false;
      END IF;
      IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='is_hidden') THEN
        ALTER TABLE users ADD COLUMN is_hidden BOOLEAN NOT NULL DEFAULT false;
      END IF;
      IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='is_virtual') THEN
        ALTER TABLE users ADD COLUMN is_virtual BOOLEAN NOT NULL DEFAULT false;
      END IF;
      IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='created_at') THEN
        ALTER TABLE users ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
      END IF;
      IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='last_active') THEN
        ALTER TABLE users ADD COLUMN last_active TIMESTAMPTZ NOT NULL DEFAULT NOW();
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM pg_constraint c
        JOIN pg_class t ON c.conrelid=t.oid
        WHERE t.relname='users' AND c.contype='u' AND c.conname='users_username_key'
      ) THEN
        BEGIN
          ALTER TABLE users ADD CONSTRAINT users_username_key UNIQUE (username);
        EXCEPTION WHEN duplicate_table OR unique_violation THEN
          RAISE NOTICE 'Skipped adding unique(users.username) due to duplicates.';
        END;
      END IF;
    END $$;

    -- 其它表按需创建
    CREATE TABLE IF NOT EXISTS tags (
      id SERIAL PRIMARY KEY,
      name TEXT NOT NULL UNIQUE,
      type TEXT NOT NULL CHECK (type IN ('positive','negative')),
      is_active BOOLEAN NOT NULL DEFAULT true,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS ratings (
      id SERIAL PRIMARY KEY,
      user_id BIGINT NOT NULL,
      rater_id BIGINT NOT NULL,
      sentiment TEXT NOT NULL CHECK (sentiment IN ('positive','negative')),
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      CONSTRAINT fk_ratings_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
      CONSTRAINT fk_ratings_rater FOREIGN KEY (rater_id) REFERENCES users(user_id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS rating_tags (
      id SERIAL PRIMARY KEY,
      rating_id INT NOT NULL REFERENCES ratings(id) ON DELETE CASCADE,
      tag_id INT NOT NULL REFERENCES tags(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS favorites (
      user_id BIGINT NOT NULL,
      favorite_user_id BIGINT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      PRIMARY KEY (user_id, favorite_user_id),
      CONSTRAINT fk_fav_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
      CONSTRAINT fk_fav_target FOREIGN KEY (favorite_user_id) REFERENCES users(user_id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS user_queries (
      id BIGSERIAL PRIMARY KEY,
      requester_id BIGINT NOT NULL,
      target_user_id BIGINT NOT NULL,
      chat_id BIGINT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_user_queries_req ON user_queries(requester_id);
    CREATE INDEX IF NOT EXISTS idx_user_queries_target ON user_queries(target_user_id);

    DO $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname='unique_pair_rating'
      ) THEN
        BEGIN
          ALTER TABLE ratings ADD CONSTRAINT unique_pair_rating UNIQUE (rater_id, user_id);
        EXCEPTION WHEN duplicate_table OR unique_violation THEN
          RAISE NOTICE 'Skipped adding unique(rater_id,user_id) due to duplicates.';
        END;
      END IF;
    END $$;

    CREATE SEQUENCE IF NOT EXISTS virtual_user_seq START 1 INCREMENT 1;
    """
    async with get_conn() as conn:
        await conn.execute(sql)
    logger.info("Schema ensure completed.")
