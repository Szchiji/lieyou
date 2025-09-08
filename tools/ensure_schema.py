import logging
from database import get_conn

logger = logging.getLogger(__name__)

async def ensure_schema():
    """
    启动自检/自愈数据库结构（兼容旧表），幂等可反复执行。
    关键改动：避免在 CREATE TABLE 时直接写死外键到 ratings(id)/tags(id)，
    改为建表后动态探测目标表主键名并条件性添加外键，防止 "column id does not exist"。
    """
    sql = """
    -- 1) users 表修复或创建
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

      -- user_id -> BIGINT
      PERFORM 1
      FROM information_schema.columns
      WHERE table_name='users' AND column_name='user_id' AND data_type='bigint';
      IF NOT FOUND THEN
        ALTER TABLE users ALTER COLUMN user_id TYPE BIGINT USING user_id::bigint;
      END IF;

      -- 主键确保
      IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        WHERE t.relname='users' AND c.contype='p'
      ) THEN
        ALTER TABLE users ADD PRIMARY KEY (user_id);
      END IF;

      -- 必要列补齐
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

      -- username 唯一（若重复会失败，需要人工清理重复再加）
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

    -- 2) tags 表：如不存在则创建（使用 id 作为主键）
    CREATE TABLE IF NOT EXISTS tags (
      id SERIAL PRIMARY KEY,
      name TEXT NOT NULL UNIQUE,
      type TEXT NOT NULL CHECK (type IN ('positive','negative')),
      is_active BOOLEAN NOT NULL DEFAULT true,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    -- 3) ratings 表：如不存在则创建（不在 CREATE 阶段强加外键，后面再条件添加）
    CREATE TABLE IF NOT EXISTS ratings (
      id SERIAL PRIMARY KEY,
      user_id BIGINT NOT NULL,
      rater_id BIGINT NOT NULL,
      sentiment TEXT NOT NULL CHECK (sentiment IN ('positive','negative')),
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    -- 3.1) 条件添加 ratings 外键到 users(user_id)
    DO $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname='fk_ratings_user'
      ) THEN
        ALTER TABLE ratings
          ADD CONSTRAINT fk_ratings_user
          FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE;
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname='fk_ratings_rater'
      ) THEN
        ALTER TABLE ratings
          ADD CONSTRAINT fk_ratings_rater
          FOREIGN KEY (rater_id) REFERENCES users(user_id) ON DELETE CASCADE;
      END IF;
    END $$;

    -- 3.2) 评价唯一约束 (rater_id, user_id)
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

    -- 4) rating_tags 表：不在 CREATE 阶段加外键，后续动态探测主键后再加
    CREATE TABLE IF NOT EXISTS rating_tags (
      id SERIAL PRIMARY KEY,
      rating_id INT NOT NULL,
      tag_id INT NOT NULL
    );

    -- 4.1) 动态探测 ratings/tags 主键列并添加外键
    DO $$
    DECLARE
      rpk TEXT;
      tpk TEXT;
    BEGIN
      -- ratings 主键列名
      SELECT a.attname
      INTO rpk
      FROM pg_index i
      JOIN pg_class c ON c.oid = i.indrelid
      JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
      WHERE c.relname='ratings' AND i.indisprimary
      LIMIT 1;

      -- 若未检测到，兜底尝试使用 id 列（如果存在）
      IF rpk IS NULL AND EXISTS (
        SELECT 1 FROM information_schema.columns WHERE table_name='ratings' AND column_name='id'
      ) THEN
        rpk := 'id';
      END IF;

      -- tags 主键列名
      SELECT a.attname
      INTO tpk
      FROM pg_index i
      JOIN pg_class c ON c.oid = i.indrelid
      JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
      WHERE c.relname='tags' AND i.indisprimary
      LIMIT 1;

      IF tpk IS NULL AND EXISTS (
        SELECT 1 FROM information_schema.columns WHERE table_name='tags' AND column_name='id'
      ) THEN
        tpk := 'id';
      END IF;

      -- 添加外键：rating_tags.rating_id -> ratings(rpk)
      IF rpk IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname='fk_rating_tags_rating'
      ) THEN
        EXECUTE format(
          'ALTER TABLE rating_tags ADD CONSTRAINT fk_rating_tags_rating FOREIGN KEY (rating_id) REFERENCES ratings(%I) ON DELETE CASCADE',
          rpk
        );
      END IF;

      -- 添加外键：rating_tags.tag_id -> tags(tpk)
      IF tpk IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname='fk_rating_tags_tag'
      ) THEN
        EXECUTE format(
          'ALTER TABLE rating_tags ADD CONSTRAINT fk_rating_tags_tag FOREIGN KEY (tag_id) REFERENCES tags(%I) ON DELETE CASCADE',
          tpk
        );
      END IF;
    END $$;

    -- 5) favorites 表（先建表，外键后置）
    CREATE TABLE IF NOT EXISTS favorites (
      user_id BIGINT NOT NULL,
      favorite_user_id BIGINT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      PRIMARY KEY (user_id, favorite_user_id)
    );

    DO $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname='fk_fav_user'
      ) THEN
        ALTER TABLE favorites
          ADD CONSTRAINT fk_fav_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE;
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname='fk_fav_target'
      ) THEN
        ALTER TABLE favorites
          ADD CONSTRAINT fk_fav_target FOREIGN KEY (favorite_user_id) REFERENCES users(user_id) ON DELETE CASCADE;
      END IF;
    END $$;

    -- 6) user_queries & 索引
    CREATE TABLE IF NOT EXISTS user_queries (
      id BIGSERIAL PRIMARY KEY,
      requester_id BIGINT NOT NULL,
      target_user_id BIGINT NOT NULL,
      chat_id BIGINT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_user_queries_req ON user_queries(requester_id);
    CREATE INDEX IF NOT EXISTS idx_user_queries_target ON user_queries(target_user_id);

    -- 7) 虚拟用户序列
    CREATE SEQUENCE IF NOT EXISTS virtual_user_seq START 1 INCREMENT 1;
    """
    async with get_conn() as conn:
        await conn.execute(sql)
    logger.info("Schema ensure completed.")
