#!/usr/bin/env python
"""
Script to create custom fields in Pipedrive for Hermes integration.

This script will:
1. Create all required custom fields in Pipedrive (Organization, Deal, Person)
2. Display the field IDs (keys) for use in field_mappings_override.py
3. Optionally replace existing fields with the same names

Usage:
    uv run python v2_migration/scripts/create_pipedrive_fields.py
    uv run python v2_migration/scripts/create_pipedrive_fields.py --replace-existing
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Dict, List

import httpx
import typer
from rich.console import Console
from rich.table import Table

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Change to project root so .env file is found
import os
os.chdir(project_root)

from app.core.config import settings

console = Console()
app = typer.Typer()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Field type mapping based on Company model
FIELD_TYPES = {
    # Numerical fields
    'hermes_id': 'int',
    'paid_invoice_count': 'int',
    'support_person_id': 'int',
    'bdr_person_id': 'int',

    # Date fields
    'created': 'date',
    'pay0_dt': 'date',
    'pay1_dt': 'date',
    'pay3_dt': 'date',
    'gclid_expiry_dt': 'date',
    'email_confirmed_dt': 'date',
    'card_saved_dt': 'date',

    # Text fields
    'tc2_cligency_url': 'varchar',
    'tc2_status': 'varchar',
    'website': 'varchar',
    'price_plan': 'varchar',
    'estimated_income': 'varchar',
    'utm_source': 'varchar',
    'utm_campaign': 'varchar',
    'gclid': 'varchar',
    'signup_questionnaire': 'text',  # Large text
}

# Fields for each entity type
ORGANIZATION_FIELDS = [
    'hermes_id',
    'paid_invoice_count',
    'tc2_cligency_url',
    'tc2_status',
    'website',
    'price_plan',
    'estimated_income',
    'support_person_id',
    'bdr_person_id',
    'signup_questionnaire',
    'utm_source',
    'utm_campaign',
    'created',
    'pay0_dt',
    'pay1_dt',
    'pay3_dt',
    'gclid',
    'gclid_expiry_dt',
    'email_confirmed_dt',
    'card_saved_dt',
]

DEAL_FIELDS = [
    'hermes_id',
    'support_person_id',
    'tc2_cligency_url',
    'signup_questionnaire',
    'utm_campaign',
    'utm_source',
    'bdr_person_id',
    'paid_invoice_count',
    'tc2_status',
    'website',
    'price_plan',
    'estimated_income',
]

PERSON_FIELDS = [
    'hermes_id',
]


async def get_existing_fields(entity_type: str) -> Dict[str, dict]:
    """Fetch existing custom fields from Pipedrive."""
    endpoint_map = {
        'organization': 'organizationFields',
        'deal': 'dealFields',
        'person': 'personFields',
    }

    endpoint = endpoint_map[entity_type]

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f'{settings.pd_base_url}/api/v1/{endpoint}',
            headers={'Accept': 'application/json'},
            params={'api_token': settings.pd_api_key},
            timeout=30.0
        )
        response.raise_for_status()
        fields = response.json().get('data', [])

        # Map field names to field objects
        return {f['name'].lower(): f for f in fields}


async def create_field(entity_type: str, field_name: str, field_type: str) -> dict:
    """Create a single custom field in Pipedrive."""
    endpoint_map = {
        'organization': 'organizationFields',
        'deal': 'dealFields',
        'person': 'personFields',
    }

    endpoint = endpoint_map[entity_type]

    field_data = {
        'name': field_name,
        'field_type': field_type
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f'{settings.pd_base_url}/api/v1/{endpoint}',
            headers={'Accept': 'application/json'},
            params={'api_token': settings.pd_api_key},
            json=field_data,
            timeout=30.0
        )
        response.raise_for_status()
        return response.json().get('data', {})


async def delete_field(entity_type: str, field_id: int) -> None:
    """Delete a custom field from Pipedrive."""
    endpoint_map = {
        'organization': 'organizationFields',
        'deal': 'dealFields',
        'person': 'personFields',
    }

    endpoint = endpoint_map[entity_type]

    async with httpx.AsyncClient() as client:
        response = await client.delete(
            f'{settings.pd_base_url}/api/v1/{endpoint}/{field_id}',
            headers={'Accept': 'application/json'},
            params={'api_token': settings.pd_api_key},
            timeout=30.0
        )
        response.raise_for_status()


async def create_fields_for_entity(
    entity_type: str,
    field_names: List[str],
    replace_existing: bool = False
) -> Dict[str, any]:
    """Create custom fields for a specific entity type."""
    results = {
        'created': [],
        'existing': [],
        'deleted': [],
        'failed': [],
    }

    console.print(f'\n[bold cyan]Processing {entity_type} fields...[/bold cyan]')

    # Get existing fields
    existing_fields = await get_existing_fields(entity_type)

    for field_name in field_names:
        field_type = FIELD_TYPES[field_name]

        # Check if field exists
        if field_name.lower() in existing_fields:
            existing_field = existing_fields[field_name.lower()]

            if replace_existing:
                try:
                    console.print(f'  Deleting existing field: [yellow]{field_name}[/yellow]')
                    await delete_field(entity_type, existing_field['id'])
                    results['deleted'].append({
                        'name': field_name,
                        'id': existing_field['id'],
                        'key': existing_field['key']
                    })
                except Exception as e:
                    console.print(f'  [red]Failed to delete {field_name}: {e}[/red]')
                    results['failed'].append({'name': field_name, 'error': str(e)})
                    continue
            else:
                console.print(f'  Field exists: [green]{field_name}[/green] (key: {existing_field["key"]})')
                results['existing'].append({
                    'name': field_name,
                    'key': existing_field['key'],
                    'type': existing_field['field_type']
                })
                continue

        # Create the field
        try:
            console.print(f'  Creating field: [cyan]{field_name}[/cyan] (type: {field_type})')
            created_field = await create_field(entity_type, field_name, field_type)
            results['created'].append({
                'name': field_name,
                'key': created_field['key'],
                'type': field_type
            })
            console.print(f'  [green]✓[/green] Created: {field_name} (key: {created_field["key"]})')
        except Exception as e:
            console.print(f'  [red]Failed to create {field_name}: {e}[/red]')
            results['failed'].append({'name': field_name, 'error': str(e)})

    return results


def display_results(all_results: dict):
    """Display results in a nice table format."""
    console.print('\n[bold green]Field Creation Summary[/bold green]\n')

    for entity_type, results in all_results.items():
        console.print(f'[bold]{entity_type.upper()}[/bold]')

        if results['created']:
            table = Table(title='Created Fields')
            table.add_column('Field Name', style='cyan')
            table.add_column('Key', style='green')
            table.add_column('Type', style='yellow')

            for field in results['created']:
                table.add_row(field['name'], field['key'], field['type'])

            console.print(table)

        if results['existing']:
            table = Table(title='Existing Fields')
            table.add_column('Field Name', style='cyan')
            table.add_column('Key', style='blue')
            table.add_column('Type', style='yellow')

            for field in results['existing']:
                table.add_row(field['name'], field['key'], field['type'])

            console.print(table)

        if results['deleted']:
            console.print(f'[yellow]Deleted {len(results["deleted"])} fields[/yellow]')

        if results['failed']:
            console.print(f'[red]Failed to create {len(results["failed"])} fields[/red]')
            for field in results['failed']:
                console.print(f'  - {field["name"]}: {field["error"]}')

        console.print()


def generate_override_file(all_results: dict):
    """Generate field_mappings_override.py file with the field keys."""
    console.print('[bold cyan]Generating field_mappings_override.py...[/bold cyan]')

    # Collect all field keys
    company_map = {}
    deal_map = {}
    contact_map = {}

    for field in all_results['organization']['created'] + all_results['organization']['existing']:
        company_map[field['name']] = field['key']

    for field in all_results['deal']['created'] + all_results['deal']['existing']:
        deal_map[field['name']] = field['key']

    for field in all_results['person']['created'] + all_results['person']['existing']:
        contact_map[field['name']] = field['key']

    # Generate the file content
    content = '''"""
Field mapping overrides for your Pipedrive account.
This file is auto-generated by scripts/create_pipedrive_fields.py
"""

COMPANY_PD_FIELD_MAP = {
'''

    for name, key in sorted(company_map.items()):
        content += f"    '{name}': '{key}',\n"

    content += '''}\n
DEAL_PD_FIELD_MAP = {
'''

    for name, key in sorted(deal_map.items()):
        content += f"    '{name}': '{key}',\n"

    content += '''}\n
CONTACT_PD_FIELD_MAP = {
'''

    for name, key in sorted(contact_map.items()):
        content += f"    '{name}': '{key}',\n"

    content += '}\n'

    # Write to file
    with open('field_mappings_override.py', 'w') as f:
        f.write(content)

    console.print('[green]✓ Created field_mappings_override.py[/green]')
    console.print('\nYou can now use these field mappings in your Hermes installation.')


@app.command()
def main(
    replace_existing: bool = typer.Option(
        False,
        '--replace-existing',
        '-r',
        help='Delete and recreate existing fields with the same names'
    )
):
    """Create custom fields in Pipedrive for Hermes integration."""

    if not settings.pd_api_key:
        console.print('[red]Error: PD_API_KEY not set in environment[/red]')
        raise typer.Exit(1)

    console.print('[bold]Hermes Pipedrive Field Creator[/bold]\n')
    console.print(f'Pipedrive URL: {settings.pd_base_url}')
    console.print(f'Replace existing: {replace_existing}\n')

    if replace_existing:
        if not typer.confirm('This will DELETE and recreate existing fields. Continue?'):
            raise typer.Exit(0)

    async def run():
        all_results = {}

        # Create organization fields
        all_results['organization'] = await create_fields_for_entity(
            'organization', ORGANIZATION_FIELDS, replace_existing
        )

        # Create deal fields
        all_results['deal'] = await create_fields_for_entity(
            'deal', DEAL_FIELDS, replace_existing
        )

        # Create person fields
        all_results['person'] = await create_fields_for_entity(
            'person', PERSON_FIELDS, replace_existing
        )

        return all_results

    # Run async operations
    all_results = asyncio.run(run())

    # Display results
    display_results(all_results)

    # Generate override file
    generate_override_file(all_results)

    console.print('[bold green]✓ Done![/bold green]')


if __name__ == '__main__':
    app()
