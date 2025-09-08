-- 全新数据库初始化（幂等）
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
    ALTER TABLE ratings ADD CONSTRAINT unique_pair_rating UNIQUE (rater_id, user_id);
  END IF;
END $$;

CREATE SEQUENCE IF NOT EXISTS virtual_user_seq START 1 INCREMENT 1;
