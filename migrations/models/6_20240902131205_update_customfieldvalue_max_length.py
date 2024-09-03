from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "customfieldvalue" ALTER COLUMN "value" TYPE VARCHAR(10000) USING "value"::VARCHAR(10000);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "customfieldvalue" ALTER COLUMN "value" TYPE VARCHAR(255) USING "value"::VARCHAR(255);"""
