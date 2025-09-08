ALTER TABLE ratings DROP CONSTRAINT IF EXISTS unique_daily_rating;
ALTER TABLE ratings DROP COLUMN IF EXISTS rating_date;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'unique_pair_rating'
    ) THEN
        ALTER TABLE ratings
        ADD CONSTRAINT unique_pair_rating UNIQUE (rater_id, user_id);
    END IF;
END $$;

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_virtual BOOLEAN NOT NULL DEFAULT false;
