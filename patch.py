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
from app.pipedrive import api

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('hermes.patch')

commands = []

'''
1	"Sam"
2	"Fionn"
3	"Maahi"
4	"Raashi"
6	"Tom"
9	"Tony"
7	"Gabe"
15	"Drew"
'''

SAM_ID = 1
FIONN_ID = 2
MAAHI_ID = 3
RAASHI_ID = 4
TOM_ID = 6
GABE_ID = 7
DAN_ID = 8
TONY_ID = 9
DREW_ID = 15

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
async def insert_admin_placeholders(db):
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

@command
async def swap_gabe_admin(db):
    '''
    Now swap gabe and tom admin ids
    '''
    from app.main_app.models import Admin

    gabe = db.exec(select(Admin).where(Admin.tc2_admin_id == 2543678)).first()
    tom = db.exec(select(Admin).where(Admin.tc2_admin_id == 85329)).first()

    print(f'Gabe currently at ID {gabe.id}')
    print(f'Tom currently at ID {tom.id}')

    print("Swapping")

    fields_to_swap = [field for field in Admin.model_fields.keys() if field != 'id']

    gabe_original = {field: getattr(gabe, field) for field in fields_to_swap}
    tom_original = {field: getattr(tom, field) for field in fields_to_swap}

    gabe.tc2_admin_id = None
    tom.tc2_admin_id = None
    db.flush()

    for field in fields_to_swap:
        setattr(gabe, field, tom_original[field])
        setattr(tom, field, gabe_original[field])

    db.add(gabe)
    db.add(tom)
    db.flush()

    print(f'Swapped: Gabe data now at ID 7, Tom data now at ID 6')


@command
async def reassign_companies_by_price_plan(db):
    from app.main_app.models import Company, Deal

    companies = db.exec(select(Company).where(Company.sales_person_id.in_([MAAHI_ID, RAASHI_ID]))).all()

    print(f'Found {len(companies)} companies with sales_person_id')

    companies_updated = 0
    deals_updated = 0

    for company in companies:
        new_sales_person_id = None

        if company.price_plan == Company.PP_ENTERPRISE:
            new_sales_person_id = FIONN_ID
        elif company.price_plan in (Company.PP_PAYG, Company.PP_STARTUP):
            if company.country == 'US':
                new_sales_person_id = TONY_ID
            else:
                new_sales_person_id = SAM_ID

        if new_sales_person_id:
            company.sales_person_id = new_sales_person_id
            db.add(company)
            companies_updated += 1

            for deal in company.deals:
                deal.admin_id = new_sales_person_id
                db.add(deal)
                deals_updated += 1

    print(f'Updated {companies_updated} companies')
    print(f'Updated {deals_updated} deals')


def _categorize_deals(deals, db):
    from app.main_app.models import Company

    deals_with_org_id = []
    deals_without_org_id = []
    no_name_count = 0

    for deal in deals:
        if not deal.name:
            no_name_count += 1
            continue

        company = db.get(Company, deal.company_id)
        if company and company.pd_org_id:
            deals_with_org_id.append((deal, company.pd_org_id))
        else:
            deals_without_org_id.append(deal)

    return deals_with_org_id, deals_without_org_id, no_name_count

def _find_matching_deal(pd_deal, deals_with_org_id, deals_without_org_id):
    def match_deal_by_substring():
        for deal, deal_org_id in deals_with_org_id:
            if deal_org_id == org_id:
                hermes_title_lower = deal.name.lower().strip()
                if hermes_title_lower in pd_title_lower or pd_title_lower in hermes_title_lower:
                    return deal
        return None

    def match_deal_exact():
        for deal in deals_without_org_id:
            if deal.name.lower().strip() == pd_title_lower:
                return deal
        return None

    title = pd_deal.get('title')
    if not title:
        return None

    pd_title_lower = title.lower().strip()
    org_id = pd_deal.get('org_id')

    if org_id:
        return match_deal_by_substring()
    else:
        return match_deal_exact()


@command
async def sync_deals_without_pd_id(db):
    """
    Find and link deals missing pd_deal_id by matching them in Pipedrive.

    Deals without pd_deal_id were never properly synced. This patch fetches all deals
    from Pipedrive and matches them to Hermes deals by company pd_org_id and deal name.

    Process:
    1. Query all Hermes deals where pd_deal_id is NULL
    2. Categorize deals by whether company has pd_org_id
    3. Fetch all deals from Pipedrive API in paginated requests (500 per page)
    4. Match using substring match (with org_id) or exact match (without org_id)

    Outcome:
    Deals missing pd_deal_id will have pd_deal_id set.
    """
    from app.main_app.models import Deal

    deals = db.exec(select(Deal).where(Deal.pd_deal_id.is_(None))).all()
    deals_with_org_id, deals_without_org_id, no_name_count = _categorize_deals(deals, db)

    print(f'Found {len(deals)} deals with pd_deal_id NULL')
    print(f'{len(deals_with_org_id)} deals have company with pd_org_id (substring match)')
    print(f'{len(deals_without_org_id)} deals have no pd_org_id (exact match)')
    print(f'{no_name_count} deals skipped - deal has no name')

    existing_pd_deal_ids = {d.pd_deal_id for d in db.exec(select(Deal).where(Deal.pd_deal_id.is_not(None))).all()}
    print(f'{len(existing_pd_deal_ids)} pd_deal_ids already exist in database')

    updated_count = 0
    skipped_count = 0
    cursor = None
    page_count = 0
    matched_deals = set()

    while True:
        params = {'limit': 500, 'cursor': cursor} if cursor else {'limit': 500}

        print(f'Fetching page {page_count + 1} from Pipedrive...')
        result = await api.pipedrive_request('deals', method='GET', query_params=params)
        pd_deals = result.get('data', [])

        if not pd_deals:
            print('No more deals returned')
            break

        print(f'Processing {len(pd_deals)} deals from page {page_count + 1}')
        page_count += 1

        for pd_deal in pd_deals:
            pd_deal_id = pd_deal['id']
            hermes_deal = _find_matching_deal(pd_deal, deals_with_org_id, deals_without_org_id)

            if hermes_deal:
                matched_deals.add(hermes_deal.id)
                if pd_deal_id in existing_pd_deal_ids:
                    skipped_count += 1
                else:
                    hermes_deal.pd_deal_id = pd_deal_id
                    db.add(hermes_deal)
                    updated_count += 1

        cursor = result.get('additional_data', {}).get('next_cursor')
        if not cursor:
            print('No more pages')
            break

        print(f'{updated_count} deals updated, {skipped_count} skipped (duplicate pd_deal_id)')

    unmatched_count = len(deals_with_org_id) + len(deals_without_org_id) - len(matched_deals)

    print(f'Processed {page_count} pages')
    print(f'Updated {updated_count} deals total')
    print(f'Skipped {skipped_count} deals (pd_deal_id already exists)')
    print(f'{unmatched_count} deals not found in Pipedrive or name mismatch')


@command
async def sync_deal_owners_from_pipedrive(db):
    """
    Sync deal admin_id from Pipedrive to correct owner assignments in Hermes.

    Some deals in Hermes have incorrect admin_id values not in SALES TEAM which causes
    wrong owner_id to sent to Pipedrive during sync. This patch will fetch the
    current owner_id from Pipedrive for these deals and updates Hermes to match.

    Process:
    1. Build a mapping of Pipedrive owner_id to Hermes admin.id for all admins
    2. Query all Hermes deals where admin_id is not in SALES TEAM
    3. Fetch all deals from Pipedrive API in paginated requests (500 per page)
    4. For each deal found in both systems, look up the owner_id from Pipedrive
    5. Map that owner_id to the correct Hermes admin.id and update the deal
    6. Continue pagination until all Pipedrive deals are processed

    Outcome:
    All deals with admin_id not in SALES TEAM will have their admin_id updated to match
    the current owner in Pipedrive, ensuring future syncs send correct owner_id.
    """
    from app.main_app.models import Admin, Deal


    admins = db.exec(select(Admin)).all()
    pd_owner_to_admin = {admin.pd_owner_id: admin.id for admin in admins}

    print(f'Loaded {len(admins)} admins')
    print(f'pd_owner_id to admin.id mapping: {len(pd_owner_to_admin)} entries')

    deals = db.exec(select(Deal).where(Deal.admin_id.not_in([SAM_ID, FIONN_ID, GABE_ID, TONY_ID, DREW_ID]))).all()
    hermes_deal_map = {deal.pd_deal_id: deal for deal in deals if deal.pd_deal_id}

    print(f'Found {len(deals)} deals')
    print(f'Of these, {len(hermes_deal_map)} have pd_deal_id set')

    updated_count = 0
    cursor = None
    page_count = 0

    while True:
        params = {'limit': 500}
        if cursor:
            params['cursor'] = cursor

        print(f'Fetching page {page_count + 1} from Pipedrive...')
        result = await api.pipedrive_request('deals', method='GET', query_params=params)
        pd_deals = result.get('data', [])

        if not pd_deals:
            print('No more deals returned')
            break

        print(f'Processing {len(pd_deals)} deals from page {page_count + 1}')
        page_count += 1

        for pd_deal in pd_deals:
            pd_deal_id = pd_deal['id']
            owner_id = pd_deal.get('owner_id')

            if pd_deal_id in hermes_deal_map and owner_id:
                hermes_admin_id = pd_owner_to_admin.get(owner_id)
                if hermes_admin_id:
                    deal = hermes_deal_map[pd_deal_id]
                    deal.admin_id = hermes_admin_id
                    db.add(deal)
                    updated_count += 1

        cursor = result.get('additional_data', {}).get('next_cursor')
        if not cursor:
            print('No more pages')
            break

        print(f'{updated_count} deals updated so far')

    print(f'Processed {page_count} pages')
    print(f'Updated {updated_count} deals total')


@click.command()
@click.argument('command', type=click.Choice([c.__name__ for c in commands]))
@click.option('--live', is_flag=True)
def patch(command, live):
    command_lookup = {c.__name__: c for c in commands}

    start = datetime.now()
    with get_session() as db:
        asyncio.run(command_lookup[command](db=db))
        if live:
            db.commit()
            print('Committing changes')
        else:
            print('Not committing changes')

    print(f'Patch took {(datetime.now() - start).total_seconds():0.2f}s')


if __name__ == '__main__':
    patch()
