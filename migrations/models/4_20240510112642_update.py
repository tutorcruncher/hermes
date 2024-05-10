from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "admin" ADD "sells_row" BOOL NOT NULL  DEFAULT False;
        ALTER TABLE "admin" ADD "sells_us" BOOL NOT NULL  DEFAULT False;
        ALTER TABLE "admin" ADD "sells_gb" BOOL NOT NULL  DEFAULT False;
        ALTER TABLE "admin" ADD "sells_au" BOOL NOT NULL  DEFAULT False;
        ALTER TABLE "admin" ADD "sells_eu" BOOL NOT NULL  DEFAULT False;
        ALTER TABLE "admin" ADD "sells_ca" BOOL NOT NULL  DEFAULT False;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "admin" DROP COLUMN "sells_row";
        ALTER TABLE "admin" DROP COLUMN "sells_us";
        ALTER TABLE "admin" DROP COLUMN "sells_gb";
        ALTER TABLE "admin" DROP COLUMN "sells_au";
        ALTER TABLE "admin" DROP COLUMN "sells_eu";
        ALTER TABLE "admin" DROP COLUMN "sells_ca";"""
