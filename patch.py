import asyncio
import os
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
    await Tortoise.generate_schemas()

commands = []

def command(func):
    commands.append(func)
    return func

# Start of patch commands

@command
async def send_companies_with_bdr_or_sales_to_tc2():
    """
    This patch sends companies with a BDR or Sales person to TC2.
    """
    print('Sending companies with BDR or Sales person to TC2')

    companies = await Company.filter(
        Q(sales_person=None) | Q(bdr_person=None)
    )

    print(f'Found {len(companies)} companies with BDR or Sales person')
    for company in companies:
        try:
            await update_client_from_company(company)
        except Exception as e:
            print(f'Error updating company {company.id}: {e}')


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
