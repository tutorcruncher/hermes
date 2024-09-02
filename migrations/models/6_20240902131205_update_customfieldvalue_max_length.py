from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "customfieldvalue" ALTER COLUMN "value" TYPE VARCHAR(512) USING "value"::VARCHAR(512);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "customfieldvalue" ALTER COLUMN "value" TYPE VARCHAR(255) USING "value"::VARCHAR(255);"""
