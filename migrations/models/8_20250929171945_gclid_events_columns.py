from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "company" ADD "pay1_dt" TIMESTAMPTZ;
        ALTER TABLE "company" ADD "gclid" VARCHAR(255);
        ALTER TABLE "company" ADD "card_saved_dt" TIMESTAMPTZ;
        ALTER TABLE "company" ADD "pay3_dt" TIMESTAMPTZ;
        ALTER TABLE "company" ADD "gclid_expiry_dt" TIMESTAMPTZ;
        ALTER TABLE "company" ADD "email_confirmed_dt" TIMESTAMPTZ;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "company" DROP COLUMN "pay1_dt";
        ALTER TABLE "company" DROP COLUMN "gclid";
        ALTER TABLE "company" DROP COLUMN "card_saved_dt";
        ALTER TABLE "company" DROP COLUMN "pay3_dt";
        ALTER TABLE "company" DROP COLUMN "gclid_expiry_dt";
        ALTER TABLE "company" DROP COLUMN "email_confirmed_dt";"""
