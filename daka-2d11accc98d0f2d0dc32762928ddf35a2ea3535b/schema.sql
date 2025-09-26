-- 配置表
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- 会员表
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
    expire_date DATE,
    checkins TEXT[] DEFAULT '{}',
    PRIMARY KEY (user_id, chat_id)
);
