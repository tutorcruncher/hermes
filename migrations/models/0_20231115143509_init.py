from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "admin" (
    "username" VARCHAR(255) NOT NULL,
    "password" VARCHAR(255),
    "id" SERIAL NOT NULL PRIMARY KEY,
    "tc2_admin_id" INT  UNIQUE,
    "pd_owner_id" INT,
    "first_name" VARCHAR(255) NOT NULL  DEFAULT '',
    "last_name" VARCHAR(255) NOT NULL  DEFAULT '',
    "timezone" VARCHAR(255) NOT NULL  DEFAULT 'Europe/London',
    "is_sales_person" BOOL NOT NULL  DEFAULT False,
    "is_support_person" BOOL NOT NULL  DEFAULT False,
    "is_bdr_person" BOOL NOT NULL  DEFAULT False,
    "sells_payg" BOOL NOT NULL  DEFAULT False,
    "sells_startup" BOOL NOT NULL  DEFAULT False,
    "sells_enterprise" BOOL NOT NULL  DEFAULT False
);
COMMENT ON COLUMN "admin"."username" IS 'Use their ACTUAL email address, not META';
CREATE TABLE IF NOT EXISTS "company" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "name" VARCHAR(255) NOT NULL,
    "tc2_agency_id" INT  UNIQUE,
    "tc2_cligency_id" INT  UNIQUE,
    "tc2_status" VARCHAR(25)   DEFAULT 'pending_email_conf',
    "pd_org_id" INT  UNIQUE,
    "created" TIMESTAMPTZ NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "price_plan" VARCHAR(255) NOT NULL  DEFAULT 'payg',
    "country" VARCHAR(255),
    "website" VARCHAR(255),
    "paid_invoice_count" INT NOT NULL  DEFAULT 0,
    "estimated_income" VARCHAR(255),
    "currency" VARCHAR(255),
    "has_booked_call" BOOL NOT NULL  DEFAULT False,
    "has_signed_up" BOOL NOT NULL  DEFAULT False,
    "bdr_person_id" INT REFERENCES "admin" ("id") ON DELETE CASCADE,
    "sales_person_id" INT NOT NULL REFERENCES "admin" ("id") ON DELETE CASCADE,
    "support_person_id" INT REFERENCES "admin" ("id") ON DELETE CASCADE
);
COMMENT ON COLUMN "company"."country" IS 'Country code, e.g. GB';
COMMENT ON TABLE "company" IS 'Represents a company.';
CREATE TABLE IF NOT EXISTS "contact" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "tc2_sr_id" INT  UNIQUE,
    "pd_person_id" INT  UNIQUE,
    "created" TIMESTAMPTZ NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "first_name" VARCHAR(255),
    "last_name" VARCHAR(255),
    "email" VARCHAR(255),
    "phone" VARCHAR(255),
    "country" VARCHAR(255),
    "company_id" INT NOT NULL REFERENCES "company" ("id") ON DELETE CASCADE
);
COMMENT ON TABLE "contact" IS 'Represents a contact, an individual who works at a company.';
CREATE TABLE IF NOT EXISTS "stage" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "pd_stage_id" INT NOT NULL UNIQUE,
    "name" VARCHAR(255) NOT NULL
);
CREATE TABLE IF NOT EXISTS "pipeline" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "pd_pipeline_id" INT NOT NULL UNIQUE,
    "name" VARCHAR(255) NOT NULL,
    "dft_entry_stage_id" INT REFERENCES "stage" ("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS "config" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "meeting_dur_mins" INT NOT NULL  DEFAULT 30,
    "meeting_buffer_mins" INT NOT NULL  DEFAULT 15,
    "meeting_min_start" VARCHAR(5) NOT NULL  DEFAULT '10:00',
    "meeting_max_end" VARCHAR(5) NOT NULL  DEFAULT '17:30',
    "enterprise_pipeline_id" INT REFERENCES "pipeline" ("id") ON DELETE CASCADE,
    "payg_pipeline_id" INT REFERENCES "pipeline" ("id") ON DELETE CASCADE,
    "startup_pipeline_id" INT REFERENCES "pipeline" ("id") ON DELETE CASCADE
);
COMMENT ON COLUMN "config"."meeting_dur_mins" IS 'The length of a newly created meeting';
COMMENT ON COLUMN "config"."meeting_buffer_mins" IS 'The buffer time before and after a meeting';
COMMENT ON COLUMN "config"."meeting_min_start" IS 'The earliest time a meeting can be booked for an admin in their timezone.';
COMMENT ON COLUMN "config"."meeting_max_end" IS 'The earliest time a meeting can be booked for an admin in their timezone.';
COMMENT ON COLUMN "config"."enterprise_pipeline_id" IS 'The pipeline that Enterprise clients will be added to';
COMMENT ON COLUMN "config"."payg_pipeline_id" IS 'The pipeline that PAYG clients will be added to';
COMMENT ON COLUMN "config"."startup_pipeline_id" IS 'The pipeline that Startup clients will be added to';
COMMENT ON TABLE "config" IS 'The model that stores the configuration for the app.';
CREATE TABLE IF NOT EXISTS "deal" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "pd_deal_id" INT  UNIQUE,
    "name" VARCHAR(255),
    "status" VARCHAR(255) NOT NULL  DEFAULT 'open',
    "admin_id" INT NOT NULL REFERENCES "admin" ("id") ON DELETE CASCADE,
    "company_id" INT NOT NULL REFERENCES "company" ("id") ON DELETE CASCADE,
    "contact_id" INT REFERENCES "contact" ("id") ON DELETE CASCADE,
    "pipeline_id" INT NOT NULL REFERENCES "pipeline" ("id") ON DELETE CASCADE,
    "stage_id" INT NOT NULL REFERENCES "stage" ("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS "meeting" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created" TIMESTAMPTZ NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "start_time" TIMESTAMPTZ,
    "end_time" TIMESTAMPTZ,
    "status" VARCHAR(255) NOT NULL  DEFAULT 'PLANNED',
    "meeting_type" VARCHAR(255) NOT NULL,
    "admin_id" INT NOT NULL REFERENCES "admin" ("id") ON DELETE CASCADE,
    "contact_id" INT NOT NULL REFERENCES "contact" ("id") ON DELETE CASCADE,
    "deal_id" INT REFERENCES "deal" ("id") ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS "aerich" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "version" VARCHAR(255) NOT NULL,
    "app" VARCHAR(100) NOT NULL,
    "content" JSONB NOT NULL
);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """
