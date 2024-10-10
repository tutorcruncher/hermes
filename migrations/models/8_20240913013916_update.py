from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "company" ADD "support_call_count" INT NOT NULL  DEFAULT 0;
        ALTER TABLE "company" ADD "sales_call_count" INT NOT NULL  DEFAULT 0;
        ALTER TABLE "company" DROP COLUMN "has_booked_call";"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "company" ADD "has_booked_call" BOOL NOT NULL  DEFAULT False;
        ALTER TABLE "company" DROP COLUMN "support_call_count";
        ALTER TABLE "company" DROP COLUMN "sales_call_count";"""
