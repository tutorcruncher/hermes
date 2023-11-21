from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "company" ADD "utm_campaign" VARCHAR(255);
        ALTER TABLE "company" ADD "utm_source" VARCHAR(255);
        """

async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "company" DROP COLUMN "utm_campaign";
        ALTER TABLE "company" DROP COLUMN "utm_source";
        """
