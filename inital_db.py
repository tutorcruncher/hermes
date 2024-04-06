from tortoise import Tortoise, run_async
from app.models import Admin, Company, Config, Contact, CustomField, Deal, Pipeline, Stage
from app.utils import logger


async def setup_database():
    """
    This function is called from scripts/initial_db.py and scripts/initial_db_test.py to set up the database when
    testing locally, to save wasting 40 mins setting this up each time I have to reset-db.
    """

    # Currently you to need to run uvicorn, login, close the server, then run this script.

    logger.info('Creating Admins')
    # Create the first Admin instance
    await Admin.update_or_create(
        id=100,
        defaults={
            'username': 'testing@tutorcruncher.com',
            'password': None,
            'tc2_admin_id': 0,
            'pd_owner_id': 0,
            'first_name': 'Testing',
            'last_name': 'Testing',
            'timezone': 'Europe/London',
            'is_sales_person': False,
            'is_support_person': False,
            'is_bdr_person': False,
            'sells_payg': False,
            'sells_startup': False,
            'sells_enterprise': False,
        },
    )

    await Admin.update_or_create(
        id=2,
        defaults={
            'username': 'fionn@tutorcruncher.com',
            'password': 'testing',
            'tc2_admin_id': 68,
            'pd_owner_id': 16532867,
            'first_name': 'Fionn',
            'last_name': 'Finegan',
            'timezone': 'Europe/London',
            'is_sales_person': True,
            'is_support_person': False,
            'is_bdr_person': False,
            'sells_payg': False,
            'sells_startup': False,
            'sells_enterprise': True,
        },
    )

    # Create the second Admin instance
    await Admin.update_or_create(
        id=1,
        defaults={
            'username': 'sam@tutorcruncher.com',
            'password': 'testing',
            'tc2_admin_id': 67,
            'pd_owner_id': 16532834,
            'first_name': 'Sam',
            'last_name': 'Linge',
            'timezone': 'Europe/London',
            'is_sales_person': True,
            'is_support_person': False,
            'is_bdr_person': False,
            'sells_payg': True,
            'sells_startup': True,
            'sells_enterprise': False,
        },
    )

    # Create the third Admin instance
    await Admin.update_or_create(
        id=3,
        defaults={
            'username': 'raashi@tutorcurnhcer.com',
            'password': 'testing',
            'tc2_admin_id': 69,
            'pd_owner_id': 0,
            'first_name': 'Raashi',
            'last_name': 'Thakran',
            'timezone': 'Europe/London',
            'is_sales_person': False,
            'is_support_person': True,
            'is_bdr_person': False,
            'sells_payg': False,
            'sells_startup': False,
            'sells_enterprise': False,
        },
    )

    # Create the fourth Admin instance
    await Admin.update_or_create(
        id=4,
        defaults={
            'username': 'maahi@tutorcruncher.com',
            'password': 'testing',
            'tc2_admin_id': 70,
            'pd_owner_id': 0,
            'first_name': 'Maahi',
            'last_name': 'Islam',
            'timezone': 'Europe/London',
            'is_sales_person': False,
            'is_support_person': True,
            'is_bdr_person': False,
            'sells_payg': False,
            'sells_startup': False,
            'sells_enterprise': False,
        },
    )

    # Create the fifth Admin instance
    await Admin.update_or_create(
        id=7,
        defaults={
            'username': 'gabe@tutorcruncher.com',
            'password': 'testing',
            'tc2_admin_id': 71,
            'pd_owner_id': 16532779,
            'first_name': 'Gabe',
            'last_name': 'Gatrill',
            'timezone': 'Europe/London',
            'is_sales_person': False,
            'is_support_person': False,
            'is_bdr_person': True,
            'sells_payg': False,
            'sells_startup': False,
            'sells_enterprise': False,
        },
    )

    # Assuming Company is a class with a create method
    logger.info('Creating Companies')
    # Create the first Company instance
    await Company.update_or_create(
        id=168,
        defaults={
            'name': 'rake dog',
            'tc2_agency_id': 23,
            'tc2_cligency_id': 1351,
            'tc2_status': 'pending_email_conf',
            'pd_org_id': 362,
            'created': '2023-11-24 09:04:59.3112+00',
            'price_plan': 'payg',
            'country': 'GB',
            'website': 'http://test.test.com',
            'paid_invoice_count': 0,
            'estimated_income': '£10,000 - £20,000',
            'currency': None,
            'has_booked_call': False,
            'has_signed_up': False,
            'utm_campaign': None,
            'utm_source': None,
            'narc': False,
            'bdr_person_id': 1,
            'sales_person_id': 3,
            'support_person_id': None,
        },
    )

    # Create the second Company instance
    await Company.update_or_create(
        id=169,
        defaults={
            'name': 'xenogenesis yearn spoon',
            'tc2_agency_id': 24,
            'tc2_cligency_id': 1412,
            'tc2_status': 'pending_email_conf',
            'pd_org_id': 363,
            'created': '2023-11-24 09:19:08.10572+00',
            'price_plan': 'startup',
            'country': 'GB',
            'website': 'http://super.trooper.com',
            'paid_invoice_count': 0,
            'estimated_income': '£50,000 - £100,000',
            'currency': None,
            'has_booked_call': False,
            'has_signed_up': False,
            'utm_campaign': None,
            'utm_source': None,
            'narc': False,
            'bdr_person_id': 1,
            'sales_person_id': 4,
            'support_person_id': None,
        },
    )

    # Create the third Company instance
    await Company.update_or_create(
        id=170,
        defaults={
            'name': 'brave meraki',
            'tc2_agency_id': 25,
            'tc2_cligency_id': 1473,
            'tc2_status': 'pending_email_conf',
            'pd_org_id': 364,
            'created': '2023-11-24 09:27:36.750212+00',
            'price_plan': 'payg',
            'country': 'GB',
            'website': 'http://test.test.com',
            'paid_invoice_count': 0,
            'estimated_income': '£50,000 - £100,000',
            'currency': None,
            'has_booked_call': False,
            'has_signed_up': False,
            'utm_campaign': None,
            'utm_source': None,
            'narc': False,
            'bdr_person_id': 1,
            'sales_person_id': 3,
            'support_person_id': None,
        },
    )

    # Create the fourth Company instance
    await Company.update_or_create(
        id=166,
        defaults={
            'name': '123456',
            'tc2_agency_id': 21,
            'tc2_cligency_id': 1229,
            'tc2_status': 'pending_email_conf',
            'pd_org_id': 360,
            'created': '2023-11-23 17:25:53.824357+00',
            'price_plan': 'payg',
            'country': 'GB',
            'website': 'http://www.onetwothree.com',
            'paid_invoice_count': 0,
            'estimated_income': 'just starting out',
            'currency': None,
            'has_booked_call': False,
            'has_signed_up': False,
            'utm_campaign': None,
            'utm_source': None,
            'narc': False,
            'bdr_person_id': 1,
            'sales_person_id': 3,
            'support_person_id': None,
        },
    )

    # Create the fifth Company instance
    await Company.update_or_create(
        id=167,
        defaults={
            'name': 'infinite fork',
            'tc2_agency_id': 22,
            'tc2_cligency_id': 1290,
            'tc2_status': 'pending_email_conf',
            'pd_org_id': 361,
            'created': '2023-11-23 17:30:59.228017+00',
            'price_plan': 'payg',
            'country': 'GB',
            'website': 'http://test.test.com',
            'paid_invoice_count': 0,
            'estimated_income': 'just starting out',
            'currency': None,
            'has_booked_call': False,
            'has_signed_up': False,
            'utm_campaign': None,
            'utm_source': None,
            'narc': False,
            'bdr_person_id': 1,
            'sales_person_id': 4,
            'support_person_id': None,
        },
    )

    logger.info('Creating Contact')
    # Create instances for the "public.contact" table
    await Contact.update_or_create(
        id=125,
        defaults={
            'tc2_sr_id': 1291,
            'pd_person_id': 173,
            'created': '2023-11-23 17:30:59.2316+00',
            'first_name': 'opulent',
            'last_name': 'yarn',
            'email': None,
            'phone': None,
            'country': None,
            'company_id': 167,
        },
    )

    await Contact.update_or_create(
        id=126,
        defaults={
            'tc2_sr_id': 1352,
            'pd_person_id': 174,
            'created': '2023-11-24 09:04:59.320119+00',
            'first_name': 'optimistic',
            'last_name': 'cherry',
            'email': 'rainy@abrasive.com',
            'phone': None,
            'country': None,
            'company_id': 168,
        },
    )

    await Contact.update_or_create(
        id=127,
        defaults={
            'tc2_sr_id': 1413,
            'pd_person_id': 175,
            'created': '2023-11-24 09:19:08.116621+00',
            'first_name': 'youthful',
            'last_name': 'pencil',
            'email': 'lock@gestalt.com',
            'phone': None,
            'country': None,
            'company_id': 169,
        },
    )

    await Contact.update_or_create(
        id=128,
        defaults={
            'tc2_sr_id': 1474,
            'pd_person_id': 176,
            'created': '2023-11-24 09:27:36.759544+00',
            'first_name': 'inquisitive',
            'last_name': 'genteel television',
            'email': 'blue@small.com',
            'phone': None,
            'country': None,
            'company_id': 170,
        },
    )

    await Contact.update_or_create(
        id=124,
        defaults={
            'tc2_sr_id': 1230,
            'pd_person_id': 172,
            'created': '2023-11-23 17:25:53.828285+00',
            'first_name': '123456',
            'last_name': '123456',
            'email': None,
            'phone': None,
            'country': None,
            'company_id': 166,
        },
    )

    logger.info('Creating CustomField')
    # Create instances for the "public.customfield" table
    await CustomField.update_or_create(
        id=1,
        defaults={
            'name': 'Website',
            'machine_name': 'website',
            'field_type': 'str',
            'hermes_field_name': 'website',
            'tc2_machine_name': None,
            'pd_field_id': '49206a74cce41f79dcb7944f2de6e0ee42a55b02',
            'linked_object_type': 'Company',
        },
    )

    await CustomField.update_or_create(
        id=2,
        defaults={
            'name': 'Paid Invoice Count',
            'machine_name': 'paid_invoice_count',
            'field_type': 'int',
            'hermes_field_name': 'paid_invoice_count',
            'tc2_machine_name': None,
            'pd_field_id': 'e2e7987002fcc6b2f0b6b1dde78e295f79c4e0b7',
            'linked_object_type': 'Company',
        },
    )

    await CustomField.update_or_create(
        id=3,
        defaults={
            'name': 'TC2 Cligency URL',
            'machine_name': 'tc2_cligency_url',
            'field_type': 'str',
            'hermes_field_name': 'tc2_cligency_url',
            'tc2_machine_name': None,
            'pd_field_id': 'dd55f5ecb2a95f89d30309ba67ef08ddd5aaa5bb',
            'linked_object_type': 'Company',
        },
    )

    await CustomField.update_or_create(
        id=4,
        defaults={
            'name': 'TC2 Status',
            'machine_name': 'tc2_status',
            'field_type': 'str',
            'hermes_field_name': 'tc2_status',
            'tc2_machine_name': None,
            'pd_field_id': '174c4a837a4eeeda6ea9850506964a7db2488229',
            'linked_object_type': 'Company',
        },
    )

    await CustomField.update_or_create(
        id=5,
        defaults={
            'name': 'UTM Source',
            'machine_name': 'utm_source',
            'field_type': 'str',
            'hermes_field_name': 'utm_source',
            'tc2_machine_name': None,
            'pd_field_id': '2fa66e880dfbabed928e0fcedb4b027f8802c8af',
            'linked_object_type': 'Company',
        },
    )

    await CustomField.update_or_create(
        id=6,
        defaults={
            'name': 'UTM Campaign',
            'machine_name': 'utm_campaign',
            'field_type': 'str',
            'hermes_field_name': 'utm_campaign',
            'tc2_machine_name': None,
            'pd_field_id': 'ee62ff350d2dd1c189d2ea023ee1823a1b94b3a1',
            'linked_object_type': 'Company',
        },
    )

    await CustomField.update_or_create(
        id=7,
        defaults={
            'name': 'Estimated Monthly Income',
            'machine_name': 'estimated_monthly_income',
            'field_type': 'str',
            'hermes_field_name': 'estimated_income',
            'tc2_machine_name': 'estimated_monthly_income',
            'pd_field_id': '2f821a5168fa642991fc5ddd3e5e49124f04ebed',
            'linked_object_type': 'Company',
        },
    )

    await CustomField.update_or_create(
        id=8,
        defaults={
            'name': 'BDR Person ID',
            'machine_name': 'bdr_person_id',
            'field_type': 'str',
            'hermes_field_name': 'bdr_person_id',
            'tc2_machine_name': 'None',
            'pd_field_id': 'd98f937eed5df4341711ba53052d257a20d47bec',
            'linked_object_type': 'Company',
        },
    )

    await CustomField.update_or_create(
        id=9,
        defaults={
            'name': 'Hermes ID',
            'machine_name': 'hermes_id',
            'field_type': 'fk_field',
            'hermes_field_name': 'id',
            'tc2_machine_name': None,
            'pd_field_id': 'ac78ff43095ad2be524b3e0533c2e3f7df91e141',
            'linked_object_type': 'Company',
        },
    )

    await CustomField.update_or_create(
        id=10,
        defaults={
            'name': 'Hermes ID',
            'machine_name': 'hermes_id_2',
            'field_type': 'fk_field',
            'hermes_field_name': 'id',
            'tc2_machine_name': None,
            'pd_field_id': '4ede82add98b0baf02f8881e88fa2c6394be0ba8',
            'linked_object_type': 'Contact',
        },
    )

    await CustomField.update_or_create(
        id=11,
        defaults={
            'name': 'Hermes ID',
            'machine_name': 'hermes_id_3',
            'field_type': 'fk_field',
            'hermes_field_name': 'id',
            'tc2_machine_name': None,
            'pd_field_id': 'f9fb48b365d26a4b88cd3953aa5b91cd574efd87',
            'linked_object_type': 'Deal',
        },
    )

    logger.info('Creating Stages')
    await Stage.update_or_create(id=1, defaults={'pd_stage_id': 7, 'name': 'PAYG Qualified'})
    await Stage.update_or_create(id=2, defaults={'pd_stage_id': 9, 'name': 'PAYG Demo Scheduled'})
    await Stage.update_or_create(id=3, defaults={'pd_stage_id': 11, 'name': 'PAYG Negotiations Started'})
    await Stage.update_or_create(id=4, defaults={'pd_stage_id': 10, 'name': 'PAYG Proposal Made'})
    await Stage.update_or_create(id=9, defaults={'pd_stage_id': 25, 'name': 'STARTUP Qualified'})
    await Stage.update_or_create(id=5, defaults={'pd_stage_id': 27, 'name': 'STARTUP Demo Scheduled'})
    await Stage.update_or_create(id=6, defaults={'pd_stage_id': 26, 'name': 'STARTUP Contact Made'})
    await Stage.update_or_create(id=7, defaults={'pd_stage_id': 29, 'name': 'STARTUP Negotiations Started'})
    await Stage.update_or_create(id=8, defaults={'pd_stage_id': 28, 'name': 'STARTUP Proposal Made'})
    await Stage.update_or_create(id=12, defaults={'pd_stage_id': 31, 'name': 'ENTERPRISE Contact Made'})
    await Stage.update_or_create(id=11, defaults={'pd_stage_id': 32, 'name': 'ENTERPRISE Demo Scheduled'})
    await Stage.update_or_create(id=10, defaults={'pd_stage_id': 30, 'name': 'ENTERPRISE Qualified'})
    await Stage.update_or_create(id=13, defaults={'pd_stage_id': 33, 'name': 'ENTERPRISE Proposal Made'})
    await Stage.update_or_create(id=14, defaults={'pd_stage_id': 34, 'name': 'ENTERPRISE Negotiations Started'})

    logger.info('Creating Pipelines')
    # Updating or Creating records in the Pipeline table
    await Pipeline.update_or_create(id=1, defaults={'pd_pipeline_id': 2, 'name': 'PAYG', 'dft_entry_stage_id': 1})
    await Pipeline.update_or_create(
        id=3, defaults={'pd_pipeline_id': 6, 'name': 'ENTERPRISE', 'dft_entry_stage_id': 10}
    )
    await Pipeline.update_or_create(id=2, defaults={'pd_pipeline_id': 5, 'name': 'STARTUP', 'dft_entry_stage_id': 9})

    logger.info('Creating Deals')
    # Updating or Creating records in the Deal table
    await Deal.update_or_create(
        id=160,
        defaults={
            'pd_deal_id': 225,
            'name': '123456',
            'status': 'open',
            'admin_id': 1,
            'company_id': 166,
            'contact_id': 124,
            'pipeline_id': 1,
            'stage_id': 1,
        },
    )
    await Deal.update_or_create(
        id=161,
        defaults={
            'pd_deal_id': 227,
            'name': 'infinite fork',
            'status': 'open',
            'admin_id': 1,
            'company_id': 167,
            'contact_id': 125,
            'pipeline_id': 1,
            'stage_id': 1,
        },
    )
    await Deal.update_or_create(
        id=162,
        defaults={
            'pd_deal_id': 229,
            'name': 'rake dog',
            'status': 'open',
            'admin_id': 1,
            'company_id': 168,
            'contact_id': 126,
            'pipeline_id': 1,
            'stage_id': 1,
        },
    )
    await Deal.update_or_create(
        id=163,
        defaults={
            'pd_deal_id': 230,
            'name': 'xenogenesis yearn spoon',
            'status': 'open',
            'admin_id': 1,
            'company_id': 169,
            'contact_id': 127,
            'pipeline_id': 2,
            'stage_id': 9,
        },
    )
    await Deal.update_or_create(
        id=164,
        defaults={
            'pd_deal_id': 231,
            'name': 'brave meraki',
            'status': 'open',
            'admin_id': 1,
            'company_id': 170,
            'contact_id': 128,
            'pipeline_id': 1,
            'stage_id': 1,
        },
    )

    # Assuming the relevant classes for each table (e.g., Config, Contact, CustomField, CustomFieldValue, Deal, HermesModel, Meeting, Pipeline, Stage) have create methods.
    logger.info('Creating Config')
    # Create instances for the "public.config" table
    await Config.update_or_create(
        id=1,
        defaults={
            'meeting_dur_mins': 30,
            'meeting_buffer_mins': 15,
            'meeting_min_start': '10:00',
            'meeting_max_end': '17:30',
            'enterprise_pipeline_id': 3,
            'payg_pipeline_id': 1,
            'startup_pipeline_id': 2,
        },
    )


async def run():
    # Initialize Tortoise
    await Tortoise.init(db_url='postgres://postgres@localhost:5432/hermes', modules={'models': ['app.models']})
    # Run your function
    await setup_database()


# Run the function with Tortoise ORM
run_async(run())
