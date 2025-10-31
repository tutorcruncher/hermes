"""
Test script for v2 to v3 migration.

This script creates test data in a v2-style database and verifies it migrates correctly to v3.
"""

import asyncio
import logging
from datetime import datetime, timezone

import asyncpg
import pytest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MigrationTest:
    """Test the migration from v2 to v3"""

    def __init__(self, v2_db_url: str, v3_db_url: str):
        self.v2_db_url = v2_db_url
        self.v3_db_url = v3_db_url
        self.v2_conn = None
        self.v3_conn = None

        # Test data IDs
        self.test_admin_id = None
        self.test_company_id = None
        self.test_contact_id = None
        self.test_pipeline_id = None
        self.test_stage_id = None
        self.test_deal_id = None

    async def connect(self):
        """Connect to databases"""
        self.v2_conn = await asyncpg.connect(self.v2_db_url)
        self.v3_conn = await asyncpg.connect(self.v3_db_url)

    async def close(self):
        """Close connections"""
        if self.v2_conn:
            await self.v2_conn.close()
        if self.v3_conn:
            await self.v3_conn.close()

    async def create_v2_test_data(self):
        """Create test data in v2 database"""
        logger.info('Creating test data in v2 database...')

        # Create admin
        self.test_admin_id = await self.v2_conn.fetchval(
            """
            INSERT INTO admin (
                tc2_admin_id, pd_owner_id, first_name, last_name, username, timezone,
                is_sales_person, is_support_person, is_bdr_person,
                sells_payg, sells_startup, sells_enterprise,
                sells_us, sells_gb, sells_au, sells_ca, sells_eu, sells_row,
                password
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
            RETURNING id
            """,
            1001,
            2001,
            'Test',
            'Admin',
            'test@example.com',
            'Europe/London',
            True,
            False,
            False,
            True,
            False,
            False,
            True,
            False,
            False,
            False,
            False,
            False,
            'hashed_password',
        )

        # Create pipeline
        self.test_pipeline_id = await self.v2_conn.fetchval(
            """
            INSERT INTO pipeline (pd_pipeline_id, name, dft_entry_stage_id)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            1,
            'Test Pipeline',
            None,
        )

        # Create stage
        self.test_stage_id = await self.v2_conn.fetchval(
            """
            INSERT INTO stage (pd_stage_id, name)
            VALUES ($1, $2)
            RETURNING id
            """,
            1,
            'Test Stage',
        )

        # Create company
        self.test_company_id = await self.v2_conn.fetchval(
            """
            INSERT INTO company (
                name, tc2_agency_id, tc2_cligency_id, pd_org_id, created,
                price_plan, country, website, currency, estimated_income,
                utm_campaign, utm_source, gclid,
                has_booked_call, has_signed_up, narc, paid_invoice_count, tc2_status,
                pay0_dt, pay1_dt, pay3_dt, gclid_expiry_dt, email_confirmed_dt, card_saved_dt,
                sales_person_id, support_person_id, bdr_person_id
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18,
                $19, $20, $21, $22, $23, $24, $25, $26, $27
            )
            RETURNING id
            """,
            'Test Company',
            123,
            456,
            789,
            datetime.now(timezone.utc),
            'payg',
            'GB',
            'https://example.com',
            'GBP',
            '10000-50000',
            'test-campaign',
            'test-source',
            'test-gclid',
            True,
            True,
            False,
            3,
            'active',
            datetime.now(timezone.utc),
            None,
            None,
            None,
            datetime.now(timezone.utc),
            None,
            self.test_admin_id,
            None,
            None,
        )

        # Create CustomField for company
        cf_id = await self.v2_conn.fetchval(
            """
            INSERT INTO customfield (
                name, machine_name, field_type, hermes_field_name,
                tc2_machine_name, pd_field_id, linked_object_type
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            'Signup Questionnaire',
            'signup_questionnaire',
            'str',
            'signup_questionnaire',
            'signup_questionnaire',
            'd4db234b06f753a951c0de94456740f270e0f2ed',
            'Company',
        )

        # Create CustomFieldValue for company
        await self.v2_conn.execute(
            """
            INSERT INTO customfieldvalue (custom_field_id, company_id, value)
            VALUES ($1, $2, $3)
            """,
            cf_id,
            self.test_company_id,
            'Test questionnaire response',
        )

        # Create contact
        self.test_contact_id = await self.v2_conn.fetchval(
            """
            INSERT INTO contact (
                tc2_sr_id, pd_person_id, created, first_name, last_name,
                email, phone, country, company_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            1001,
            2001,
            datetime.now(timezone.utc),
            'John',
            'Doe',
            'john@example.com',
            '+1234567890',
            'GB',
            self.test_company_id,
        )

        # Create deal
        self.test_deal_id = await self.v2_conn.fetchval(
            """
            INSERT INTO deal (
                pd_deal_id, name, status, admin_id, pipeline_id, stage_id,
                company_id, contact_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
            """,
            3001,
            'Test Deal',
            'open',
            self.test_admin_id,
            self.test_pipeline_id,
            self.test_stage_id,
            self.test_company_id,
            self.test_contact_id,
        )

        # Create CustomFields for deal
        deal_cf_id = await self.v2_conn.fetchval(
            """
            INSERT INTO customfield (
                name, machine_name, field_type, hermes_field_name,
                tc2_machine_name, pd_field_id, linked_object_type
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            'Website',
            'website',
            'str',
            'website',
            'website',
            '54c7fbdf915c9a8fd73dde335942cc72ebea9b9e',
            'Deal',
        )

        await self.v2_conn.execute(
            """
            INSERT INTO customfieldvalue (custom_field_id, deal_id, value)
            VALUES ($1, $2, $3)
            """,
            deal_cf_id,
            self.test_deal_id,
            'https://deal-example.com',
        )

        # Create meeting
        await self.v2_conn.execute(
            """
            INSERT INTO meeting (
                created, start_time, end_time, status, meeting_type,
                admin_id, contact_id, deal_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            datetime.now(timezone.utc),
            datetime.now(timezone.utc),
            datetime.now(timezone.utc),
            'PLANNED',
            'sales',
            self.test_admin_id,
            self.test_contact_id,
            self.test_deal_id,
        )

        logger.info('Created test data in v2 database')

    async def verify_v3_data(self):
        """Verify that test data was correctly migrated to v3"""
        logger.info('Verifying v3 data...')

        # Verify admin
        admin = await self.v3_conn.fetchrow('SELECT * FROM admin WHERE tc2_admin_id = $1', 1001)
        assert admin is not None, 'Admin not found'
        assert admin['first_name'] == 'Test'
        assert admin['last_name'] == 'Admin'
        assert admin['is_sales_person'] is True
        logger.info('✓ Admin migrated correctly')

        # Verify pipeline and stage
        pipeline = await self.v3_conn.fetchrow('SELECT * FROM pipeline WHERE pd_pipeline_id = $1', 1)
        assert pipeline is not None, 'Pipeline not found'
        logger.info('✓ Pipeline migrated correctly')

        stage = await self.v3_conn.fetchrow('SELECT * FROM stage WHERE pd_stage_id = $1', 1)
        assert stage is not None, 'Stage not found'
        logger.info('✓ Stage migrated correctly')

        # Verify company
        company = await self.v3_conn.fetchrow('SELECT * FROM company WHERE tc2_cligency_id = $1', 456)
        assert company is not None, 'Company not found'
        assert company['name'] == 'Test Company'
        assert company['country'] == 'GB'
        assert company['website'] == 'https://example.com'
        assert company['price_plan'] == 'payg'
        assert company['paid_invoice_count'] == 3
        # Check CustomField was migrated to direct field
        assert company['signup_questionnaire'] == 'Test questionnaire response'
        logger.info('✓ Company migrated correctly (including CustomFields)')

        # Verify contact
        contact = await self.v3_conn.fetchrow('SELECT * FROM contact WHERE tc2_sr_id = $1', 1001)
        assert contact is not None, 'Contact not found'
        assert contact['first_name'] == 'John'
        assert contact['last_name'] == 'Doe'
        assert contact['email'] == 'john@example.com'
        logger.info('✓ Contact migrated correctly')

        # Verify deal
        deal = await self.v3_conn.fetchrow('SELECT * FROM deal WHERE pd_deal_id = $1', 3001)
        assert deal is not None, 'Deal not found'
        assert deal['name'] == 'Test Deal'
        assert deal['status'] == 'open'
        # Check CustomField was migrated to direct field
        assert deal['website'] == 'https://deal-example.com'
        logger.info('✓ Deal migrated correctly (including CustomFields)')

        # Verify meeting
        meeting_count = await self.v3_conn.fetchval('SELECT COUNT(*) FROM meeting WHERE admin_id = $1', admin['id'])
        assert meeting_count == 1, 'Meeting not found'
        logger.info('✓ Meeting migrated correctly')

        logger.info('✓ All v3 data verified!')

    async def run_test(self):
        """Run the migration test"""
        try:
            await self.connect()
            await self.create_v2_test_data()

            # Run the actual migration script
            from migrate_v2_to_v3 import v2Tov3Migrator

            migrator = v2Tov3Migrator(self.v2_db_url, self.v3_db_url)
            await migrator.run()

            # Verify the results
            await self.verify_v3_data()

            logger.info('✓ Migration test PASSED!')
            return True

        except Exception as e:
            logger.error(f'Migration test FAILED: {e}', exc_info=True)
            return False
        finally:
            await self.close()


async def main():
    """Main entry point for test"""
    # Use test databases
    v2_db_url = 'postgresql://postgres@localhost:5432/hermes_test_v2'
    v3_db_url = 'postgresql://postgres@localhost:5432/hermes_test_v3'

    logger.info('=== Migration Test ===')
    logger.info('This will create test databases and verify migration')

    test = MigrationTest(v2_db_url, v3_db_url)
    success = await test.run_test()

    if success:
        logger.info('✓ Test completed successfully!')
        return 0
    else:
        logger.error('✗ Test failed!')
        return 1


if __name__ == '__main__':
    exit_code = asyncio.run(main())
    exit(exit_code)
