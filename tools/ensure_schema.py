import logging
from database import get_conn

logger = logging.getLogger(__name__)

async def ensure_schema():
    """
    兼容老库的 Schema 自检/自愈（幂等）。
    核心策略：
    - 不更改 users 现有主键（避免影响 evaluations/favorites 等既有外键）
    - 为 users.user_id 创建并填充数据，并加唯一约束，作为新外键的目标
    - 其它表先创建，外键后置；rating_tags 外键动态探测 ratings/tags 的主键
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

    -- 1) 标准化 users：确保有 user_id 列，填充数据，并为其建立唯一约束（不改动现有主键）
    DO $$
    DECLARE
      upk TEXT;         -- 现有 users 主键列名（若有）
      has_user_id BOOLEAN;
      has_id BOOLEAN;
      has_nulls BOOLEAN;
      uniq_exists BOOLEAN;
    BEGIN
      -- 若存在 id 但无 user_id，先重命名最常见旧列
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
          RAISE NOTICE 'users.id not found when renaming';
        END;
      END IF;

      -- 若仍无 user_id，则新增
      SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='users' AND column_name='user_id'
      ) INTO has_user_id;

      IF NOT has_user_id THEN
        ALTER TABLE users ADD COLUMN user_id BIGINT;
      END IF;

      -- 检测当前主键列
      SELECT a.attname
      INTO upk
      FROM pg_index i
      JOIN pg_class c ON c.oid = i.indrelid
      JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
      WHERE c.relname='users' AND i.indisprimary
      LIMIT 1;

      -- 用旧主键列填充 user_id（仅填充空值）
      IF upk IS NOT NULL AND upk <> 'user_id' THEN
        EXECUTE format('UPDATE users SET user_id = %I::bigint WHERE user_id IS NULL', upk);
      END IF;

      -- 统一类型 BIGINT
      BEGIN
        ALTER TABLE users ALTER COLUMN user_id TYPE BIGINT USING user_id::bigint;
      EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'users.user_id cannot be cast to BIGINT; please clean data manually.';
      END;

      -- 尝试设置 NOT NULL（若失败则忽略，后续外键仍可引用唯一列）
      SELECT EXISTS (SELECT 1 FROM users WHERE user_id IS NULL) INTO has_nulls;
      IF NOT has_nulls THEN
        BEGIN
          ALTER TABLE users ALTER COLUMN user_id SET NOT NULL;
        EXCEPTION WHEN others THEN
          RAISE NOTICE 'Could not set users.user_id NOT NULL; continuing.';
        END;
      END IF;

      -- 若尚无对 user_id 的唯一约束，则添加（不替换现有主键）
      SELECT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class t ON c.conrelid=t.oid
        WHERE t.relname='users' AND c.contype='u' AND c.conkey = ARRAY[
          (SELECT attnum FROM pg_attribute WHERE attrelid='users'::regclass AND attname='user_id')
        ]
      ) INTO uniq_exists;

      IF NOT uniq_exists THEN
        -- 约束命名为 users_user_id_key，如重名则使用索引方案兜底
        BEGIN
          ALTER TABLE users ADD CONSTRAINT users_user_id_key UNIQUE (user_id);
        EXCEPTION WHEN duplicate_table OR unique_violation THEN
          -- 若有重复 user_id，请先清理数据
          RAISE NOTICE 'Unique(users.user_id) not added (maybe duplicates exist).';
        WHEN duplicate_object THEN
          -- 可能已有同义的唯一索引
          RAISE NOTICE 'users.user_id unique already exists by another name.';
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

      -- username 唯一（若重复会失败，需要先清理）
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

    -- 2) tags（独立）
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

    -- 3.1) 外键到 users(user_id)（要求 user_id 上有唯一/主键约束）
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_ratings_user') THEN
        ALTER TABLE ratings
          ADD CONSTRAINT fk_ratings_user
          FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE;
      END IF;

      IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_ratings_rater') THEN
        ALTER TABLE ratings
          ADD CONSTRAINT fk_ratings_rater
          FOREIGN KEY (rater_id) REFERENCES users(user_id) ON DELETE CASCADE;
      END IF;
    END $$;

    -- 3.2) 评价唯一约束
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='unique_pair_rating') THEN
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

    -- 5) favorites：兼容老表（如果已存在且列名不同，尝试增补新列并回填）
    CREATE TABLE IF NOT EXISTS favorites (
      user_id BIGINT,
      favorite_user_id BIGINT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    -- 列补齐（适配旧列名 user_pkid / target_user_pkid）
    DO $$
    DECLARE
      has_user_id BOOLEAN;
      has_fav_id BOOLEAN;
      has_user_pkid BOOLEAN;
      has_target_pkid BOOLEAN;
    BEGIN
      SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='favorites' AND column_name='user_id') INTO has_user_id;
      SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='favorites' AND column_name='favorite_user_id') INTO has_fav_id;
      SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='favorites' AND column_name='user_pkid') INTO has_user_pkid;
      SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='favorites' AND column_name='target_user_pkid') INTO has_target_pkid;

      IF NOT has_user_id THEN
        ALTER TABLE favorites ADD COLUMN user_id BIGINT;
      END IF;
      IF NOT has_fav_id THEN
        ALTER TABLE favorites ADD COLUMN favorite_user_id BIGINT;
      END IF;

      -- 从旧列名回填
      IF has_user_pkid THEN
        UPDATE favorites SET user_id = COALESCE(user_id, user_pkid::bigint);
      END IF;
      IF has_target_pkid THEN
        UPDATE favorites SET favorite_user_id = COALESCE(favorite_user_id, target_user_pkid::bigint);
      END IF;

      -- 复合唯一（替代 PK；避免与旧 PK/外键冲突）
      IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname='favorites_user_fav_unique'
      ) THEN
        BEGIN
          ALTER TABLE favorites ADD CONSTRAINT favorites_user_fav_unique UNIQUE (user_id, favorite_user_id);
        EXCEPTION WHEN unique_violation THEN
          RAISE NOTICE 'Duplicate favorites (user_id,favorite_user_id); unique not added.';
        END;
      END IF;
    END $$;

    -- 外键后置（指向 users.user_id；不影响旧外键继续存在）
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_fav_user_userid') THEN
        ALTER TABLE favorites
          ADD CONSTRAINT fk_fav_user_userid FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE;
      END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_fav_target_userid') THEN
        ALTER TABLE favorites
          ADD CONSTRAINT fk_fav_target_userid FOREIGN KEY (favorite_user_id) REFERENCES users(user_id) ON DELETE CASCADE;
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
