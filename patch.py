import asyncio
import os

from app.base_schema import build_custom_field_schema
from app.pipedrive._process import _process_pd_organisation
from app.pipedrive._schema import Organisation, PipedriveEvent
from app.pipedrive.api import pipedrive_request, get_and_create_or_update_organisation

os.environ.setdefault('LOGFIRE_IGNORE_NO_CONFIG', '1')

from datetime import datetime
import click

from app.main import TORTOISE_ORM
from app.tc2.tasks import update_client_from_company
from tortoise.expressions import Q
from tortoise import Tortoise
from app.models import Company
import logfire

async def init():
    # Initialize Tortoise ORM
    await Tortoise.init(config=TORTOISE_ORM)
    await build_custom_field_schema()
    await Tortoise.generate_schemas()


commands = []

def command(func):
    commands.append(func)
    return func

# Start of patch commands

@command
async def update_companies_from_pipedrive_organisations_with_missing_bdr_sales_info():
    """
    This patch gets all companies with missing BDR or Sales person and updates them from Pipedrive,
    then updates the TC2 cligencies
    """
    # Get companies to update
    companies = await Company.filter(
        Q(sales_person_id=None) | Q(bdr_person_id=None)
    )
    print(f'Sending {len(companies)} companies with BDR or Sales person to TC2')
    # make request to get companies from Pipedrive
    for company in companies:
        try:
            # get Organisation from Pipedrive
            pd_data = await pipedrive_request(f'organizations/{company.pd_org_id}')
            mock_event = {
                'meta': {'action': 'updated', 'object': 'organization'},
                'current': pd_data['data'],
                'previous': None
            }
            event_instance = PipedriveEvent(**mock_event)
            event_instance.current and await event_instance.current.a_validate()


            # Update Company from Organisation
            await _process_pd_organisation(current_pd_org=event_instance.current, old_pd_org=None)

            try:
                # Update company in TC2
                company = await Company.get(id=company.id)
                await update_client_from_company(company)
            except Exception as e:
                print(f'Error updating cligency for company {company.id}: {e}')

        except Exception as e:
            print(f'Error updating company from org {company.id}: {e}')
            continue

@command
async def update_pd_org_price_plans():
    """
    This patch sends a webhook to Pipedrive to update the price plan of all companies with a price plan
    """
    companies = await Company.exclude(price_plan=None)
    print(f'{len(companies)} companies with price plan to update')
    companies_updated = 0
    for company in companies:
        try:
            await get_and_create_or_update_organisation(company)
            companies_updated += 1
        except Exception as e:
            print(f'Error updating company {company.id}: {e}')
            continue

    print(f'Updated {companies_updated} companies')


# End of patch commands

@click.command()
@click.argument('command', type=click.Choice([c.__name__ for c in commands]))
def patch(command):
    asyncio.run(main(command))

async def main(command):
    await init()

    command_lookup = {c.__name__: c for c in commands}

    start = datetime.now()
    with logfire.span('patch.py {command=}', command=command):
        await command_lookup[command]()

    print(f'Patch took {(datetime.now() - start).total_seconds():0.2f}s')

if __name__ == '__main__':
    patch()
