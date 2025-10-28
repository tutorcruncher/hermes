"""
Data migration script from Hermes v2 (Tortoise ORM) to Hermes v3 (SQLModel).

This script:
1. Reads data from v2 database (with CustomField/CustomFieldValue tables)
2. Transforms it to v3 structure (with direct fields using field mappings)
3. Writes data to v3 database

Usage:
    # Make sure v3 schema is created first (run migrations)
    cd v3
    make migrate

    # Then run this script
    python scripts/migrate_v2_to_v3.py

    # Or with custom database URLs:
    v2_DATABASE_URL=postgresql://... v3_DATABASE_URL=postgresql://... python scripts/migrate_v2_to_v3.py
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

import asyncpg

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class v2Tov3Migrator:
    """Migrates data from Hermes v2 to Hermes v3"""

    def __init__(self, v2_db_url: str, v3_db_url: str):
        self.v2_db_url = v2_db_url
        self.v3_db_url = v3_db_url
        self.v2_conn = None
        self.v3_conn = None

        # Mapping of v2 IDs to v3 IDs for foreign key relationships
        self.admin_id_map = {}
        self.company_id_map = {}
        self.contact_id_map = {}
        self.deal_id_map = {}
        self.pipeline_id_map = {}
        self.stage_id_map = {}

    def ensure_timezone_aware(self, dt):
        """Convert timezone-naive datetime to timezone-aware (UTC)"""
        if dt is None:
            return None
        # If already timezone-aware, convert to UTC
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc)
        # If naive, assume UTC and make it aware
        return dt.replace(tzinfo=timezone.utc)

    async def connect(self):
        """Connect to both databases"""
        logger.info('Connecting to v2 database...')
        self.v2_conn = await asyncpg.connect(self.v2_db_url)
        logger.info('Connecting to v3 database...')
        self.v3_conn = await asyncpg.connect(self.v3_db_url)
        logger.info('Connected to both databases')

    async def close(self):
        """Close database connections"""
        if self.v2_conn:
            await self.v2_conn.close()
        if self.v3_conn:
            await self.v3_conn.close()
        logger.info('Closed database connections')

    async def get_custom_field_values(self, entity_type: str, entity_id: int) -> dict:
        """
        Get all custom field values for an entity from v2.

        Returns dict mapping field machine_name to value.
        """
        query = f"""
            SELECT cf.machine_name, cf.hermes_field_name, cfv.value
            FROM customfieldvalue cfv
            JOIN customfield cf ON cfv.custom_field_id = cf.id
            WHERE cfv.{entity_type.lower()}_id = $1
        """
        rows = await self.v2_conn.fetch(query, entity_id)

        result = {}
        for row in rows:
            field_name = row['hermes_field_name'] or row['machine_name']
            if field_name:
                result[field_name] = row['value']
        return result

    async def migrate_admins(self):
        """Migrate Admin records from v2 to v3"""
        logger.info('Migrating Admins...')

        v2_admins = await self.v2_conn.fetch('SELECT * FROM admin ORDER BY id')
        logger.info(f'Found {len(v2_admins)} admins in v2')

        for v2_admin in v2_admins:
            v3_id = await self.v3_conn.fetchval(
                """
                INSERT INTO admin (
                    tc2_admin_id, pd_owner_id, first_name, last_name, username, timezone,
                    is_sales_person, is_support_person, is_bdr_person,
                    sells_payg, sells_startup, sells_enterprise,
                    sells_us, sells_gb, sells_au, sells_ca, sells_eu, sells_row
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18)
                RETURNING id
                """,
                v2_admin['tc2_admin_id'],
                v2_admin['pd_owner_id'],
                v2_admin['first_name'],
                v2_admin['last_name'],
                v2_admin['username'],
                v2_admin['timezone'],
                v2_admin['is_sales_person'],
                v2_admin['is_support_person'],
                v2_admin['is_bdr_person'],
                v2_admin['sells_payg'],
                v2_admin['sells_startup'],
                v2_admin['sells_enterprise'],
                v2_admin['sells_us'],
                v2_admin['sells_gb'],
                v2_admin['sells_au'],
                v2_admin['sells_ca'],
                v2_admin['sells_eu'],
                v2_admin['sells_row'],
            )
            self.admin_id_map[v2_admin['id']] = v3_id

        logger.info(f'Migrated {len(self.admin_id_map)} admins')

    async def migrate_pipelines(self):
        """Migrate Pipeline records from v2 to v3"""
        logger.info('Migrating Pipelines...')

        v2_pipelines = await self.v2_conn.fetch('SELECT * FROM pipeline ORDER BY id')
        logger.info(f'Found {len(v2_pipelines)} pipelines in v2')

        for v2_pipeline in v2_pipelines:
            v3_id = await self.v3_conn.fetchval(
                """
                INSERT INTO pipeline (pd_pipeline_id, name)
                VALUES ($1, $2)
                RETURNING id
                """,
                v2_pipeline['pd_pipeline_id'],
                v2_pipeline['name'],
            )
            self.pipeline_id_map[v2_pipeline['id']] = v3_id

        logger.info(f'Migrated {len(self.pipeline_id_map)} pipelines')

    async def migrate_stages(self):
        """Migrate Stage records from v2 to v3"""
        logger.info('Migrating Stages...')

        v2_stages = await self.v2_conn.fetch('SELECT * FROM stage ORDER BY id')
        logger.info(f'Found {len(v2_stages)} stages in v2')

        for v2_stage in v2_stages:
            v3_id = await self.v3_conn.fetchval(
                """
                INSERT INTO stage (pd_stage_id, name)
                VALUES ($1, $2)
                RETURNING id
                """,
                v2_stage['pd_stage_id'],
                v2_stage['name'],
            )
            self.stage_id_map[v2_stage['id']] = v3_id

        logger.info(f'Migrated {len(self.stage_id_map)} stages')

    async def update_pipeline_dft_entry_stages(self):
        """Update pipeline dft_entry_stage_id after stages are migrated"""
        logger.info('Updating pipeline default entry stages...')

        v2_pipelines = await self.v2_conn.fetch('SELECT id, dft_entry_stage_id FROM pipeline ORDER BY id')

        updated_count = 0
        for v2_pipeline in v2_pipelines:
            if v2_pipeline['dft_entry_stage_id']:
                v3_pipeline_id = self.pipeline_id_map.get(v2_pipeline['id'])
                v3_stage_id = self.stage_id_map.get(v2_pipeline['dft_entry_stage_id'])

                if v3_pipeline_id and v3_stage_id:
                    await self.v3_conn.execute(
                        """
                        UPDATE pipeline SET dft_entry_stage_id = $1 WHERE id = $2
                        """,
                        v3_stage_id,
                        v3_pipeline_id,
                    )
                    updated_count += 1

        logger.info(f'Updated {updated_count} pipeline default entry stages')

    async def migrate_config(self):
        """Migrate Config record from v2 to v3"""
        logger.info('Migrating Config...')

        v2_config = await self.v2_conn.fetchrow('SELECT * FROM config LIMIT 1')
        if not v2_config:
            logger.info('No config found in v2, skipping')
            return

        # Map pipeline IDs
        payg_pipeline_id = (
            self.pipeline_id_map.get(v2_config['payg_pipeline_id']) if v2_config['payg_pipeline_id'] else None
        )
        startup_pipeline_id = (
            self.pipeline_id_map.get(v2_config['startup_pipeline_id']) if v2_config['startup_pipeline_id'] else None
        )
        enterprise_pipeline_id = (
            self.pipeline_id_map.get(v2_config['enterprise_pipeline_id'])
            if v2_config['enterprise_pipeline_id']
            else None
        )

        await self.v3_conn.execute(
            """
            INSERT INTO config (
                meeting_dur_mins, meeting_buffer_mins, meeting_min_start, meeting_max_end,
                payg_pipeline_id, startup_pipeline_id, enterprise_pipeline_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            v2_config['meeting_dur_mins'],
            v2_config['meeting_buffer_mins'],
            v2_config['meeting_min_start'],
            v2_config['meeting_max_end'],
            payg_pipeline_id,
            startup_pipeline_id,
            enterprise_pipeline_id,
        )

        logger.info('Migrated config')

    async def migrate_companies(self):
        """Migrate Company records from v2 to v3, including custom fields"""
        logger.info('Migrating Companies...')

        # Fetch companies with timestamps converted to UTC
        v2_companies = await self.v2_conn.fetch("""
            SELECT id, name, tc2_agency_id, tc2_cligency_id, pd_org_id,
                   created AT TIME ZONE 'UTC' as created,
                   price_plan, country, website, currency, estimated_income,
                   utm_campaign, utm_source, gclid, has_booked_call, has_signed_up, narc,
                   paid_invoice_count, tc2_status,
                   pay0_dt AT TIME ZONE 'UTC' as pay0_dt,
                   pay1_dt AT TIME ZONE 'UTC' as pay1_dt,
                   pay3_dt AT TIME ZONE 'UTC' as pay3_dt,
                   gclid_expiry_dt AT TIME ZONE 'UTC' as gclid_expiry_dt,
                   email_confirmed_dt AT TIME ZONE 'UTC' as email_confirmed_dt,
                   card_saved_dt AT TIME ZONE 'UTC' as card_saved_dt,
                   sales_person_id, support_person_id, bdr_person_id
            FROM company ORDER BY id
        """)
        logger.info(f'Found {len(v2_companies)} companies in v2')

        for v2_company in v2_companies:
            # Get custom field values
            custom_fields = await self.get_custom_field_values('company', v2_company['id'])

            # Extract fields that should be in v3 direct fields (not in v2 model but in CustomFields)
            # These were stored in CustomFieldValue in v2, but are now direct fields in v3
            signup_questionnaire = custom_fields.get('signup_questionnaire')

            # Convert sales_person_id
            sales_person_id = self.admin_id_map.get(v2_company['sales_person_id'])
            support_person_id = (
                self.admin_id_map.get(v2_company['support_person_id']) if v2_company['support_person_id'] else None
            )
            bdr_person_id = self.admin_id_map.get(v2_company['bdr_person_id']) if v2_company['bdr_person_id'] else None

            if not sales_person_id:
                logger.warning(f'Company {v2_company["id"]} has invalid sales_person_id, skipping')
                continue

            v3_id = await self.v3_conn.fetchval(
                """
                INSERT INTO company (
                    name, tc2_agency_id, tc2_cligency_id, pd_org_id, created,
                    price_plan, country, website, currency, estimated_income,
                    utm_campaign, utm_source, gclid, signup_questionnaire,
                    has_booked_call, has_signed_up, narc, paid_invoice_count, tc2_status,
                    pay0_dt, pay1_dt, pay3_dt, gclid_expiry_dt, email_confirmed_dt, card_saved_dt,
                    sales_person_id, support_person_id, bdr_person_id
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26, $27, $28)
                RETURNING id
                """,
                v2_company['name'],
                v2_company['tc2_agency_id'],
                v2_company['tc2_cligency_id'],
                v2_company['pd_org_id'],
                v2_company['created'],
                v2_company['price_plan'],
                v2_company['country'],
                v2_company['website'],
                v2_company['currency'],
                v2_company['estimated_income'],
                v2_company['utm_campaign'],
                v2_company['utm_source'],
                v2_company['gclid'],
                signup_questionnaire,
                v2_company['has_booked_call'],
                v2_company['has_signed_up'],
                v2_company['narc'],
                v2_company['paid_invoice_count'],
                v2_company['tc2_status'],
                v2_company['pay0_dt'],
                v2_company['pay1_dt'],
                v2_company['pay3_dt'],
                v2_company['gclid_expiry_dt'],
                v2_company['email_confirmed_dt'],
                v2_company['card_saved_dt'],
                sales_person_id,
                support_person_id,
                bdr_person_id,
            )
            self.company_id_map[v2_company['id']] = v3_id

        logger.info(f'Migrated {len(self.company_id_map)} companies')

    async def migrate_contacts(self):
        """Migrate Contact records from v2 to v3"""
        logger.info('Migrating Contacts...')

        v2_contacts = await self.v2_conn.fetch("""
            SELECT id, tc2_sr_id, pd_person_id,
                   created AT TIME ZONE 'UTC' as created,
                   first_name, last_name, email, phone, country, company_id
            FROM contact ORDER BY id
        """)
        logger.info(f'Found {len(v2_contacts)} contacts in v2')

        for v2_contact in v2_contacts:
            company_id = self.company_id_map.get(v2_contact['company_id'])
            if not company_id:
                logger.warning(f'Contact {v2_contact["id"]} has invalid company_id, skipping')
                continue

            v3_id = await self.v3_conn.fetchval(
                """
                INSERT INTO contact (
                    tc2_sr_id, pd_person_id, created, first_name, last_name,
                    email, phone, country, company_id
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
                """,
                v2_contact['tc2_sr_id'],
                v2_contact['pd_person_id'],
                v2_contact['created'],
                v2_contact['first_name'],
                v2_contact['last_name'],
                v2_contact['email'],
                v2_contact['phone'],
                v2_contact['country'],
                company_id,
            )
            self.contact_id_map[v2_contact['id']] = v3_id

        logger.info(f'Migrated {len(self.contact_id_map)} contacts')

    async def migrate_deals(self):
        """Migrate Deal records from v2 to v3, including custom fields"""
        logger.info('Migrating Deals...')

        v2_deals = await self.v2_conn.fetch('SELECT * FROM deal ORDER BY id')
        logger.info(f'Found {len(v2_deals)} deals in v2')

        for v2_deal in v2_deals:
            # Get custom field values for fields that are now direct in v3
            custom_fields = await self.get_custom_field_values('deal', v2_deal['id'])

            # Map foreign keys
            admin_id = self.admin_id_map.get(v2_deal['admin_id'])
            pipeline_id = self.pipeline_id_map.get(v2_deal['pipeline_id'])
            stage_id = self.stage_id_map.get(v2_deal['stage_id'])
            company_id = self.company_id_map.get(v2_deal['company_id'])
            contact_id = self.contact_id_map.get(v2_deal['contact_id']) if v2_deal['contact_id'] else None

            if not all([admin_id, pipeline_id, stage_id, company_id]):
                logger.warning(f'Deal {v2_deal["id"]} has invalid foreign keys, skipping')
                continue

            # Extract fields from CustomFields that are now direct fields in v3
            support_person_id = (
                int(custom_fields['support_person_id']) if custom_fields.get('support_person_id') else None
            )
            bdr_person_id = int(custom_fields['bdr_person_id']) if custom_fields.get('bdr_person_id') else None
            paid_invoice_count = (
                int(custom_fields['paid_invoice_count']) if custom_fields.get('paid_invoice_count') else 0
            )
            tc2_status = custom_fields.get('tc2_status')
            tc2_cligency_url = custom_fields.get('tc2_cligency_url')
            website = custom_fields.get('website')
            price_plan = custom_fields.get('price_plan')
            estimated_income = custom_fields.get('estimated_monthly_income')
            signup_questionnaire = custom_fields.get('signup_questionnaire')
            utm_campaign = custom_fields.get('utm_campaign')
            utm_source = custom_fields.get('utm_source')

            v3_id = await self.v3_conn.fetchval(
                """
                INSERT INTO deal (
                    pd_deal_id, name, status, admin_id, pipeline_id, stage_id, company_id, contact_id,
                    support_person_id, bdr_person_id, paid_invoice_count, tc2_status, tc2_cligency_url, website,
                    price_plan, estimated_income, signup_questionnaire, utm_campaign, utm_source
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
                RETURNING id
                """,
                v2_deal['pd_deal_id'],
                v2_deal['name'],
                v2_deal['status'],
                admin_id,
                pipeline_id,
                stage_id,
                company_id,
                contact_id,
                support_person_id,
                bdr_person_id,
                paid_invoice_count,
                tc2_status,
                tc2_cligency_url,
                website,
                price_plan,
                estimated_income,
                signup_questionnaire,
                utm_campaign,
                utm_source,
            )
            self.deal_id_map[v2_deal['id']] = v3_id

        logger.info(f'Migrated {len(self.deal_id_map)} deals')

    async def migrate_meetings(self):
        """Migrate Meeting records from v2 to v3"""
        logger.info('Migrating Meetings...')

        v2_meetings = await self.v2_conn.fetch("""
            SELECT id,
                   created AT TIME ZONE 'UTC' as created,
                   start_time AT TIME ZONE 'UTC' as start_time,
                   end_time AT TIME ZONE 'UTC' as end_time,
                   status, meeting_type, admin_id, contact_id, deal_id
            FROM meeting ORDER BY id
        """)
        logger.info(f'Found {len(v2_meetings)} meetings in v2')

        for v2_meeting in v2_meetings:
            # Map foreign keys
            admin_id = self.admin_id_map.get(v2_meeting['admin_id'])
            contact_id = self.contact_id_map.get(v2_meeting['contact_id'])
            deal_id = self.deal_id_map.get(v2_meeting['deal_id']) if v2_meeting['deal_id'] else None

            if not all([admin_id, contact_id]):
                logger.warning(f'Meeting {v2_meeting["id"]} has invalid foreign keys, skipping')
                continue

            # Get company_id from contact
            company_id = await self.v3_conn.fetchval('SELECT company_id FROM contact WHERE id = $1', contact_id)

            await self.v3_conn.execute(
                """
                INSERT INTO meeting (
                    created, start_time, end_time, status, meeting_type,
                    admin_id, contact_id, company_id, deal_id
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                v2_meeting['created'],
                v2_meeting['start_time'],
                v2_meeting['end_time'],
                v2_meeting['status'],
                v2_meeting['meeting_type'],
                admin_id,
                contact_id,
                company_id,
                deal_id,
            )

        logger.info(f'Migrated {len(v2_meetings)} meetings')

    async def verify_migration(self):
        """Verify that the migration was successful"""
        logger.info('Verifying migration...')

        checks = [
            ('admin', len(self.admin_id_map)),
            ('pipeline', len(self.pipeline_id_map)),
            ('stage', len(self.stage_id_map)),
            ('company', len(self.company_id_map)),
            ('contact', len(self.contact_id_map)),
            ('deal', len(self.deal_id_map)),
        ]

        all_good = True
        for table, expected_count in checks:
            actual_count = await self.v3_conn.fetchval(f'SELECT COUNT(*) FROM {table}')
            if actual_count == expected_count:
                logger.info(f'✓ {table}: {actual_count} records')
            else:
                logger.error(f'✗ {table}: expected {expected_count}, got {actual_count}')
                all_good = False

        if all_good:
            logger.info('✓ Migration verification passed!')
        else:
            logger.error('✗ Migration verification failed')

    async def run(self):
        """Run the full migration"""
        try:
            await self.connect()

            # Run migrations in dependency order
            await self.migrate_admins()
            await self.migrate_pipelines()
            await self.migrate_stages()
            await self.update_pipeline_dft_entry_stages()  # Update pipelines after stages exist
            await self.migrate_config()
            await self.migrate_companies()
            await self.migrate_contacts()
            await self.migrate_deals()
            await self.migrate_meetings()

            await self.verify_migration()

            logger.info('Migration completed successfully!')

        except Exception as e:
            logger.error(f'Migration failed: {e}', exc_info=True)
            raise
        finally:
            await self.close()


async def main():
    """Main entry point"""
    # Get database URLs from environment or use defaults
    v2_db_url = os.environ.get('v2_DATABASE_URL', 'postgresql://postgres@localhost:5432/hermes')
    v3_db_url = os.environ.get('v3_DATABASE_URL', 'postgresql://postgres@localhost:5432/hermes_v3')

    logger.info('=== Hermes v2 to v3 Data Migration ===')
    logger.info(f'v2 Database: {v2_db_url}')
    logger.info(f'v3 Database: {v3_db_url}')

    if input('Continue with migration? (yes/no): ').lower() != 'yes':
        logger.info('Migration cancelled')
        return

    migrator = v2Tov3Migrator(v2_db_url, v3_db_url)
    await migrator.run()


if __name__ == '__main__':
    asyncio.run(main())
