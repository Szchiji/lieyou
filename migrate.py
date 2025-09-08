import os
import asyncio
import glob
import asyncpg
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migrate")

async def run():
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set")
    conn = await asyncpg.connect(dsn)
    try:
        files = sorted(glob.glob("migrations/*.sql"))
        logger.info(f"Found {len(files)} migration files")
        for f in files:
            logger.info(f"Applying migration: {f}")
            sql = open(f, "r", encoding="utf-8").read()
            try:
                await conn.execute(sql)
            except Exception as e:
                logger.error(f"Migration {f} failed: {e}")
                raise
        logger.info("All migrations applied.")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(run())
