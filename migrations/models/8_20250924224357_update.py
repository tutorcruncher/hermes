from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "company" ADD "pay3_date" TIMESTAMPTZ;
        ALTER TABLE "company" ADD "pay1_date" TIMESTAMPTZ;
        ALTER TABLE "company" ADD "gclid" VARCHAR(255);
        ALTER TABLE "company" ADD "gclid_expiry_date" VARCHAR(255);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "company" DROP COLUMN "pay3_date";
        ALTER TABLE "company" DROP COLUMN "pay1_date";
        ALTER TABLE "company" DROP COLUMN "gclid";
        ALTER TABLE "company" DROP COLUMN "gclid_expiry_date";"""
