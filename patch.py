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
async def fill_missing_pd_deal_ids(live, db):
    """
    Find deals in Hermes with pd_deal_id null and match them with existing deals in Pipedrive.
    """
    print('Starting patch to fill missing pd_deal_id values')

    hermes_id_field = DEAL_PD_FIELD_MAP.get('hermes_id')
    deals_missing_pd_id = db.exec(select(Deal).where(Deal.pd_deal_id.is_(None))).all()
    print(f'Found {len(deals_missing_pd_id)} deals with missing pd_deal_id')

    matched_count = 0
    unmatched_count = 0
    error_count = 0

    for deal in deals_missing_pd_id:
        try:
            company = deal.company
            if not company or not company.pd_org_id:
                print(f'Deal {deal.id} ({deal.name}) has no company or pd_org_id, skipping')
                unmatched_count += 1
                continue

            hermes_deal_id = deal.id
            company_name = company.name
            pd_org_id = company.pd_org_id

            pd_deals = await get_deals_by_org_id(pd_org_id)

            # Try to match by hermes_id custom field
            matched_pd_deal = None
            for pd_deal in pd_deals:
                custom_fields = pd_deal.get('custom_fields', {})
                pd_hermes_id = custom_fields.get(hermes_id_field)

                # Convert to int if it's a string
                if pd_hermes_id:
                    try:
                        pd_hermes_id = int(pd_hermes_id)
                    except (ValueError, TypeError):
                        pass

                if pd_hermes_id == hermes_deal_id:
                    matched_pd_deal = pd_deal
                    break

            if matched_pd_deal:
                # Update deal directly
                deal.pd_deal_id = matched_pd_deal['id']
                db.add(deal)
                print(f' Matched deal {hermes_deal_id} ({deal.name}) with Pipedrive deal {matched_pd_deal["id"]}')
                matched_count += 1
            else:
                print(
                    f' No Pipedrive deal found for Hermes deal {hermes_deal_id} ({deal.name}) '
                    f'in org {pd_org_id} ({company_name})'
                )
                unmatched_count += 1

        except Exception as e:
            print(f'Error processing deal {deal.id}: {e}')
            error_count += 1

    # Commit if live
    if matched_count > 0:
        if live:
            db.commit()
            print(f'Updated {matched_count} deals with pd_deal_id')
        else:
            print('not live, not committing.')

    print('=' * 80)
    print('Patch complete!')
    print(f'Matched: {matched_count}')
    print(f'Not matched: {unmatched_count}')
    print(f'Errors: {error_count}')
    print('=' * 80)


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
