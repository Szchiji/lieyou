import logging
from database import get_conn

logger = logging.getLogger(__name__)

async def ensure_schema():
    """
    启动自检/自愈数据库结构（兼容老库）。
    关键点：
    - 无论老库 users 主键叫什么（id/uid/...），最终统一成 user_id BIGINT 主键
    - 在标准化 users 之后，才添加/修复依赖它的外键
    - 其它表先创建后补外键；rating_tags 外键动态探测 ratings/tags 的主键列名
    """
    sql = """
    -- 0) 如不存在则创建 users（不会覆盖既有表）
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

    -- 1) 标准化 users：确保存在 user_id 且作为主键
    DO $$
    DECLARE
      upk TEXT;         -- 现有主键列名
      pkname TEXT;      -- 现有主键约束名
      has_user_id BOOLEAN;
      has_id BOOLEAN;
      has_nulls BOOLEAN;
    BEGIN
      -- 如果有 id 列且没有 user_id，则先重命名（最常见旧结构）
      SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='users' AND column_name='user_id'
      ) INTO has_user_id;

      SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='users' AND column_name='id'
      ) INTO has_id;

      IF NOT has_user_id AND has_id THEN
        BEGIN
          ALTER TABLE users RENAME COLUMN id TO user_id;
        EXCEPTION WHEN undefined_column THEN
          -- 容忍极端情况
          RAISE NOTICE 'users.id not found when renaming';
        END;
      END IF;

      -- 若仍无 user_id，补列
      SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='users' AND column_name='user_id'
      ) INTO has_user_id;

      IF NOT has_user_id THEN
        ALTER TABLE users ADD COLUMN user_id BIGINT;
      END IF;

      -- 查找当前 users 主键列（如果有）
      SELECT a.attname
      INTO upk
      FROM pg_index i
      JOIN pg_class c ON c.oid = i.indrelid
      JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
      WHERE c.relname='users' AND i.indisprimary
      LIMIT 1;

      -- 若已有主键且主键列不是 user_id，则把旧主键列的数据复制到 user_id（仅填充空值）
      IF upk IS NOT NULL AND upk <> 'user_id' THEN
        EXECUTE format('UPDATE users SET user_id = %I::bigint WHERE user_id IS NULL', upk);
      END IF;

      -- 将 user_id 类型统一 BIGINT（容错转换）
      BEGIN
        ALTER TABLE users ALTER COLUMN user_id TYPE BIGINT USING user_id::bigint;
      EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'users.user_id cannot be cast to BIGINT; please clean data manually.';
      END;

      -- 如 user_id 仍有 NULL，尽量使用 upk 填充一次
      IF upk IS NOT NULL AND upk <> 'user_id' THEN
        EXECUTE format('UPDATE users SET user_id = %I::bigint WHERE user_id IS NULL', upk);
      END IF;

      -- 再检查是否有 NULL
      SELECT EXISTS (SELECT 1 FROM users WHERE user_id IS NULL) INTO has_nulls;
      IF has_nulls THEN
        RAISE NOTICE 'users.user_id still has NULLs; primary key change may fail.';
      END IF;

      -- 取现有主键约束名
      SELECT c.conname
      INTO pkname
      FROM pg_constraint c
      JOIN pg_class t ON c.conrelid = t.oid
      WHERE t.relname='users' AND c.contype='p'
      LIMIT 1;

      -- 如果当前主键不是 user_id，则切换主键到 user_id
      IF pkname IS NOT NULL THEN
        IF upk IS NOT NULL AND upk <> 'user_id' THEN
          BEGIN
            EXECUTE format('ALTER TABLE users DROP CONSTRAINT %I', pkname);
          EXCEPTION WHEN undefined_object THEN
            -- 容忍
            NULL;
          END;
          BEGIN
            ALTER TABLE users ADD PRIMARY KEY (user_id);
          EXCEPTION WHEN not_null_violation OR unique_violation THEN
            RAISE EXCEPTION 'Switch primary key to user_id failed. Please ensure user_id is unique and NOT NULL.';
          END;
        END IF;
      ELSE
        -- 没有主键则直接设 user_id 为主键
        BEGIN
          ALTER TABLE users ADD PRIMARY KEY (user_id);
        EXCEPTION WHEN not_null_violation OR unique_violation THEN
          RAISE EXCEPTION 'Add primary key on user_id failed. Please ensure user_id is unique and NOT NULL.';
        END;
      END IF;

      -- 确保 user_id 非空
      SELECT EXISTS (SELECT 1 FROM users WHERE user_id IS NULL) INTO has_nulls;
      IF NOT has_nulls THEN
        BEGIN
          ALTER TABLE users ALTER COLUMN user_id SET NOT NULL;
        EXCEPTION WHEN others THEN
          -- 容忍（部分老库可能无法立即 SET NOT NULL）
          RAISE NOTICE 'Could not set users.user_id NOT NULL; continuing.';
        END;
      END IF;

      -- 其它列补齐（幂等）
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

      -- username 唯一（如有重复会失败，需要先清理）
      IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class t ON c.conrelid=t.oid
        WHERE t.relname='users' AND c.contype='u' AND c.conname='users_username_key'
      ) THEN
        BEGIN
          ALTER TABLE users ADD CONSTRAINT users_username_key UNIQUE (username);
        EXCEPTION WHEN unique_violation THEN
          RAISE NOTICE 'Duplicate usernames detected; unique(users.username) not added.';
        END;
      END IF;
    END $$;

    -- 2) tags
    CREATE TABLE IF NOT EXISTS tags (
      id SERIAL PRIMARY KEY,
      name TEXT NOT NULL UNIQUE,
      type TEXT NOT NULL CHECK (type IN ('positive','negative')),
      is_active BOOLEAN NOT NULL DEFAULT true,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    -- 3) ratings（先不加外键，后置）
    CREATE TABLE IF NOT EXISTS ratings (
      id SERIAL PRIMARY KEY,
      user_id BIGINT NOT NULL,
      rater_id BIGINT NOT NULL,
      sentiment TEXT NOT NULL CHECK (sentiment IN ('positive','negative')),
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    -- 3.1) 外键到 users(user_id)
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

    -- 3.2) 评价唯一约束
    DO $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname='unique_pair_rating'
      ) THEN
        BEGIN
          ALTER TABLE ratings ADD CONSTRAINT unique_pair_rating UNIQUE (rater_id, user_id);
        EXCEPTION WHEN unique_violation THEN
          RAISE NOTICE 'Duplicate pairs in ratings; unique(rater_id,user_id) not added.';
        END;
      END IF;
    END $$;

    -- 4) rating_tags（外键后置，动态探测）
    CREATE TABLE IF NOT EXISTS rating_tags (
      id SERIAL PRIMARY KEY,
      rating_id INT NOT NULL,
      tag_id INT NOT NULL
    );

    DO $$
    DECLARE
      rpk TEXT;
      tpk TEXT;
    BEGIN
      -- ratings 主键列名
      SELECT a.attname INTO rpk
      FROM pg_index i
      JOIN pg_class c ON c.oid = i.indrelid
      JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
      WHERE c.relname='ratings' AND i.indisprimary
      LIMIT 1;

      IF rpk IS NULL AND EXISTS (
        SELECT 1 FROM information_schema.columns WHERE table_name='ratings' AND column_name='id'
      ) THEN
        rpk := 'id';
      END IF;

      -- tags 主键列名
      SELECT a.attname INTO tpk
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

      IF rpk IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname='fk_rating_tags_rating'
      ) THEN
        EXECUTE format(
          'ALTER TABLE rating_tags ADD CONSTRAINT fk_rating_tags_rating FOREIGN KEY (rating_id) REFERENCES ratings(%I) ON DELETE CASCADE',
          rpk
        );
      END IF;

      IF tpk IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname='fk_rating_tags_tag'
      ) THEN
        EXECUTE format(
          'ALTER TABLE rating_tags ADD CONSTRAINT fk_rating_tags_tag FOREIGN KEY (tag_id) REFERENCES tags(%I) ON DELETE CASCADE',
          tpk
        );
      END IF;
    END $$;

    -- 5) favorites（外键后置）
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

    -- 6) user_queries + 索引
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
