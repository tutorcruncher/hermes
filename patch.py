#!/usr/bin/env python3
"""
Patch to fill missing pd_deal_id values for existing deals.

This script finds deals in Hermes where pd_deal_id is NULL and matches them
with existing deals in Pipedrive using the hermes_id custom field.
"""

import asyncio
import logging
from datetime import datetime

import click
from sqlmodel import select

from app.core.database import get_session
from app.main_app.models import Deal
from app.pipedrive import api
from app.pipedrive.field_mappings import DEAL_PD_FIELD_MAP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('hermes.patch')

commands = []


def command(func):
    commands.append(func)
    return func


async def get_deals_by_org_id(org_id: int) -> list[dict]:
    try:
        result = await api.pipedrive_request('deals', method='GET', query_params={'org_id': org_id, 'limit': 500})
        return result.get('data', [])
    except Exception as e:
        print(f'Failed to get deals for org_id {org_id}: {e}')
        return []


@command
async def insert_admin_placeholders(live, db):
    """
    Swap Daniel and Tony's data, then duplicate Drew at ID 15.

    Current: Daniel at ID 9, Tony at ID 8, Drew at ID 13
    Target: Tony data at ID 9, Daniel data at ID 8, Drew data at ID 15
    """
    from app.main_app.models import Admin

    print('Starting patch to fix admin IDs')

    # Find Daniel, Tony, and Drew
    daniel = db.exec(select(Admin).where(Admin.tc2_admin_id == 2068452)).first()
    tony = db.exec(select(Admin).where(Admin.tc2_admin_id == 2947656)).first()
    drew = db.exec(select(Admin).where(Admin.tc2_admin_id == 4253776)).first()

    print(f'Daniel currently at ID {daniel.id}')
    print(f'Tony currently at ID {tony.id}')
    print(f'Drew currently at ID {drew.id}')

    # Swap Daniel and Tony's data (not their IDs!)
    print('Swapping Daniel and Tony data...')

    # Get all field names except 'id'
    fields_to_swap = [field for field in Admin.model_fields.keys() if field != 'id']

    # Save the original values before clearing
    tony_original = {field: getattr(tony, field) for field in fields_to_swap}
    daniel_original = {field: getattr(daniel, field) for field in fields_to_swap}

    # Temporarily set tc2_admin_id to None to avoid unique constraint violation
    tony.tc2_admin_id = None
    daniel.tc2_admin_id = None
    db.flush()

    # Swap the fields using saved values
    for field in fields_to_swap:
        setattr(tony, field, daniel_original[field])
        setattr(daniel, field, tony_original[field])

    db.add(tony)
    db.add(daniel)
    db.flush()

    print(f'Swapped: Tony data now at ID 9, Daniel data now at ID 8')

    # Duplicate Drew's record at ID 15 with real data, leave ID 13 as placeholder
    print(f'Duplicating Drew from ID {drew.id} to ID 15...')

    # Save Drew's data
    drew_data = {field: getattr(drew, field) for field in Admin.model_fields.keys() if field != 'id'}
    drew_data['id'] = 15

    # Clear Drew's unique fields at ID 13 (make it a placeholder)
    drew.tc2_admin_id = None
    drew.pd_owner_id = None
    db.add(drew)
    db.flush()

    # Create the duplicate at ID 15 with Drew's real data
    drew_duplicate = Admin(**drew_data)
    db.add(drew_duplicate)
    db.flush()

    print(f'Drew duplicated: placeholder at ID 13, real Drew at ID 15')

    if live:
        db.commit()
        print('Committing changes')
    else:
        print('not committing changes')



@click.command()
@click.argument('command', type=click.Choice([c.__name__ for c in commands]))
@click.option('--live', is_flag=True)
def patch(command, live):
    command_lookup = {c.__name__: c for c in commands}

    start = datetime.now()
    with get_session() as db:
        asyncio.run(command_lookup[command](live=live, db=db))

    print(f'Patch took {(datetime.now() - start).total_seconds():0.2f}s')


if __name__ == '__main__':
    patch()
