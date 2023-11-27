from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "customfield" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "name" VARCHAR(255) NOT NULL,
    "machine_name" VARCHAR(255),
    "field_type" VARCHAR(255) NOT NULL,
    "hermes_field_name" VARCHAR(255),
    "tc2_machine_name" VARCHAR(255),
    "pd_field_id" VARCHAR(255),
    "linked_object_type" VARCHAR(255) NOT NULL,
    CONSTRAINT "uid_customfield_machine_3ef6e9" UNIQUE ("machine_name", "linked_object_type")
);
COMMENT ON COLUMN "customfield"."field_type" IS 'The type of field.';
COMMENT ON COLUMN "customfield"."hermes_field_name" IS 'If this is connected to data from the Hermes model, this is the field name. Eg: `website`';
COMMENT ON COLUMN "customfield"."tc2_machine_name" IS 'The machine name of the Custom Field in TC2, if not in the normal data.';
COMMENT ON COLUMN "customfield"."pd_field_id" IS 'The ID of the Custom Field in Pipedrive';
COMMENT ON COLUMN "customfield"."linked_object_type" IS 'The name of the model this is linked to, (\"Company\", \"Contact\", \"Deal\", \"Meeting\")';
COMMENT ON TABLE "customfield" IS 'Used to store the custom fields that we have in Pipedrive/TC. When the app is started, we run';
        CREATE TABLE IF NOT EXISTS "customfieldvalue" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "value" VARCHAR(255) NOT NULL,
    "company_id" INT REFERENCES "company" ("id") ON DELETE CASCADE,
    "contact_id" INT REFERENCES "contact" ("id") ON DELETE CASCADE,
    "custom_field_id" INT NOT NULL REFERENCES "customfield" ("id") ON DELETE CASCADE,
    "deal_id" INT REFERENCES "deal" ("id") ON DELETE CASCADE,
    "meeting_id" INT REFERENCES "meeting" ("id") ON DELETE CASCADE
);
        CREATE TABLE IF NOT EXISTS "hermesmodel" (
    "id" SERIAL NOT NULL PRIMARY KEY
);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "customfield";
        DROP TABLE IF EXISTS "customfieldvalue";
        DROP TABLE IF EXISTS "hermesmodel";"""
