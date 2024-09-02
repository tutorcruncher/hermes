from tortoise import BaseDBAsyncClient

async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "customfieldvalue" ALTER COLUMN "value" DROP NOT NULL;
    """

async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "customfieldvalue" ALTER COLUMN "value" SET NOT NULL;
    """
