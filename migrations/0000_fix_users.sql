-- 统一/修复 users 表结构到当前代码所需的样子
DO $$
BEGIN
  -- 1) 若 user_id 不存在但 id 存在，则将 id 重命名为 user_id
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='users' AND column_name='user_id'
  ) AND EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='users' AND column_name='id'
  ) THEN
    ALTER TABLE users RENAME COLUMN id TO user_id;
  END IF;

  -- 2) 若 user_id 仍不存在，则新增（极端情况：没有 id 也没有 user_id）
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='users' AND column_name='user_id'
  ) THEN
    ALTER TABLE users ADD COLUMN user_id BIGINT;
  END IF;

  -- 3) user_id 类型统一为 BIGINT
  PERFORM 1
  FROM information_schema.columns
  WHERE table_name='users' AND column_name='user_id' AND data_type='bigint';
  IF NOT FOUND THEN
    ALTER TABLE users
      ALTER COLUMN user_id TYPE BIGINT USING user_id::bigint;
  END IF;

  -- 4) 确保 user_id 为主键
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint c
    JOIN pg_class t ON c.conrelid = t.oid
    WHERE t.relname='users' AND c.contype='p'
  ) THEN
    ALTER TABLE users ADD PRIMARY KEY (user_id);
  END IF;

  -- 5) 必要列补齐
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

  -- 6) username 唯一约束（若不存在则添加）
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint c
    JOIN pg_class t ON c.conrelid = t.oid
    WHERE t.relname='users' AND c.contype='u' AND c.conname='users_username_key'
  ) THEN
    -- 如果已存在重复 username，这一步会失败。遇到失败请先手动清理重复数据。
    ALTER TABLE users ADD CONSTRAINT users_username_key UNIQUE (username);
  END IF;
END $$;

-- 兜底：如果 users 根本不存在，按新结构创建
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
