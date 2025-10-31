#!/usr/bin/env python
"""
System setup script for initializing Hermes.
Fetches pipelines and stages from Pipedrive and allows configuration.
"""

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import List

import httpx
import typer
from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table
from sqlmodel import select

from app.core.config import settings
from app.core.database import get_session
from app.main_app.models import Admin, Config, Pipeline, Stage
from app.pipedrive.api import pipedrive_request
from app.pipedrive.field_mappings import (
    _DEFAULT_COMPANY_PD_FIELD_MAP,
    _DEFAULT_CONTACT_PD_FIELD_MAP,
    _DEFAULT_DEAL_PD_FIELD_MAP,
    COMPANY_PD_FIELD_MAP,
    CONTACT_PD_FIELD_MAP,
    DEAL_PD_FIELD_MAP,
)

console = Console()
app = typer.Typer()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def get_pipelines() -> List[dict]:
    """Fetch all pipelines from Pipedrive"""
    try:
        result = await pipedrive_request('pipelines', method='GET')
        return result.get('data', [])
    except Exception as e:
        logger.error(f'Failed to fetch pipelines: {e}')
        raise


async def get_stages(pipeline_id: int) -> List[dict]:
    """Fetch all stages for a specific pipeline from Pipedrive"""
    try:
        result = await pipedrive_request('stages', method='GET', query_params={'pipeline_id': pipeline_id})
        return result.get('data', [])
    except Exception as e:
        logger.error(f'Failed to fetch stages for pipeline {pipeline_id}: {e}')
        raise


async def sync_pipelines_and_stages():
    """Sync pipelines and stages from Pipedrive to local database"""
    console.print('[bold cyan]Fetching pipelines from Pipedrive...[/bold cyan]')

    pipelines = await get_pipelines()

    if not pipelines:
        console.print('[red]No pipelines found in Pipedrive![/red]')
        return None

    db = get_session()

    # Create all stages first (since pipelines reference them)
    all_stages = {}
    for pd_pipeline in pipelines:
        pipeline_id = pd_pipeline['id']
        console.print(f'Fetching stages for pipeline: {pd_pipeline["name"]}')

        stages = await get_stages(pipeline_id)

        for pd_stage in stages:
            # Check if stage already exists
            existing_stage = db.exec(select(Stage).where(Stage.pd_stage_id == pd_stage['id'])).first()

            if not existing_stage:
                stage = db.create(Stage(pd_stage_id=pd_stage['id'], name=pd_stage['name']))
                all_stages[pd_stage['id']] = stage
            else:
                all_stages[pd_stage['id']] = existing_stage

    # Now create/update pipelines
    pipeline_objects = []
    for pd_pipeline in pipelines:
        # Get the first stage as default entry stage
        stages = await get_stages(pd_pipeline['id'])
        if not stages:
            console.print(f'[yellow]Warning: Pipeline {pd_pipeline["name"]} has no stages, skipping[/yellow]')
            continue

        first_stage = stages[0]
        dft_stage = all_stages[first_stage['id']]

        # Check if pipeline already exists
        existing_pipeline = db.exec(select(Pipeline).where(Pipeline.pd_pipeline_id == pd_pipeline['id'])).first()

        if not existing_pipeline:
            pipeline = db.create(
                Pipeline(pd_pipeline_id=pd_pipeline['id'], name=pd_pipeline['name'], dft_entry_stage_id=dft_stage.id)
            )
            pipeline_objects.append(pipeline)
        else:
            pipeline_objects.append(existing_pipeline)

    console.print(f'[green]✓ Synced {len(pipeline_objects)} pipelines and {len(all_stages)} stages[/green]')

    # Don't close the session yet - return it so display_pipelines can use it
    return pipeline_objects, db


def display_pipelines(pipelines: List[Pipeline]):
    """Display pipelines in a table"""
    table = Table(title='Available Pipelines')
    table.add_column('Index', style='cyan', no_wrap=True)
    table.add_column('ID', style='magenta')
    table.add_column('Name', style='green')
    table.add_column('Default Stage', style='yellow')

    for idx, pipeline in enumerate(pipelines, 1):
        table.add_row(str(idx), str(pipeline.pd_pipeline_id), pipeline.name, pipeline.dft_entry_stage.name)

    console.print(table)


async def select_default_stages(pipelines: List[Pipeline], db):
    """Allow user to select default entry stage for each pipeline"""
    console.print('\n[bold cyan]Select default entry stage for each pipeline[/bold cyan]')

    for pipeline in pipelines:
        console.print(f'\n[bold]Pipeline: {pipeline.name}[/bold]')

        # Get all stages for this pipeline
        stages = await get_stages(pipeline.pd_pipeline_id)

        # Display stages
        table = Table(title=f'Stages for {pipeline.name}')
        table.add_column('Index', style='cyan', no_wrap=True)
        table.add_column('Name', style='green')

        for idx, stage in enumerate(stages, 1):
            table.add_row(str(idx), stage['name'])

        console.print(table)

        # Get user selection
        stage_idx = IntPrompt.ask(
            f'Select default entry stage for {pipeline.name}',
            default=1,
            choices=[str(i) for i in range(1, len(stages) + 1)],
        )

        selected_stage = stages[stage_idx - 1]

        # Update pipeline
        stage_obj = db.exec(select(Stage).where(Stage.pd_stage_id == selected_stage['id'])).first()

        if stage_obj:
            pipeline.dft_entry_stage_id = stage_obj.id
            db.add(pipeline)
            db.commit()
            console.print(f'[green]✓ Set {selected_stage["name"]} as default stage[/green]')


def configure_pipeline_mapping(pipelines: List[Pipeline]):
    """Configure which pipelines to use for PAYG, Startup, and Enterprise"""
    console.print('\n[bold cyan]Configure pipeline mapping[/bold cyan]')

    display_pipelines(pipelines)

    db = get_session()

    # Check if config already exists
    existing_config = db.exec(select(Config).limit(1)).first()

    # Get user selections
    payg_idx = IntPrompt.ask(
        'Select pipeline for PAYG clients', default=1, choices=[str(i) for i in range(1, len(pipelines) + 1)]
    )

    startup_idx = IntPrompt.ask(
        'Select pipeline for Startup clients',
        default=2 if len(pipelines) > 1 else 1,
        choices=[str(i) for i in range(1, len(pipelines) + 1)],
    )

    enterprise_idx = IntPrompt.ask(
        'Select pipeline for Enterprise clients',
        default=3 if len(pipelines) > 2 else 1,
        choices=[str(i) for i in range(1, len(pipelines) + 1)],
    )

    # Create or update config
    if existing_config:
        existing_config.payg_pipeline_id = pipelines[payg_idx - 1].id
        existing_config.startup_pipeline_id = pipelines[startup_idx - 1].id
        existing_config.enterprise_pipeline_id = pipelines[enterprise_idx - 1].id
        db.add(existing_config)
        db.commit()
        console.print('[green]✓ Updated existing configuration[/green]')
    else:
        db.create(
            Config(
                payg_pipeline_id=pipelines[payg_idx - 1].id,
                startup_pipeline_id=pipelines[startup_idx - 1].id,
                enterprise_pipeline_id=pipelines[enterprise_idx - 1].id,
            )
        )
        console.print('[green]✓ Created new configuration[/green]')

    # Display summary
    console.print('\n[bold]Configuration Summary:[/bold]')
    console.print(f'PAYG Pipeline: {pipelines[payg_idx - 1].name}')
    console.print(f'Startup Pipeline: {pipelines[startup_idx - 1].name}')
    console.print(f'Enterprise Pipeline: {pipelines[enterprise_idx - 1].name}')

    db.close()


@app.command()
def setup():
    """Run the complete system setup"""
    console.print('[bold cyan]Hermes System Setup[/bold cyan]\n')

    if settings.pd_api_key == 'test-key':
        console.print('[red]Error: Pipedrive API key not configured![/red]')
        console.print('Please set PD_API_KEY in your .env file')
        raise typer.Exit(1)

    if not Confirm.ask('[cyan]This will reset the database. Are you sure?[/cyan]', default=False):
        console.print('Setup cancelled')
        raise typer.Exit(0)

    console.print('[cyan]Resetting database...[/cyan]')

    result = subprocess.run(['make', 'reset-db'], capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f'[red]Failed to reset database: {result.stderr}[/red]')
        raise typer.Exit(1)
    console.print('[green]✓ Database reset complete[/green]\n')

    try:
        # Sync pipelines and stages
        pipelines, db = asyncio.run(sync_pipelines_and_stages())

        if not pipelines:
            console.print('[red]No pipelines found to configure![/red]')
            db.close()
            raise typer.Exit(1)

        # Display pipelines
        display_pipelines(pipelines)

        # Select default stages for each pipeline
        asyncio.run(select_default_stages(pipelines, db))

        # Configure pipeline mapping
        configure_pipeline_mapping(pipelines)

        db.close()

        # Setup field mappings
        console.print('\n')
        setup_field_mappings()

        # Setup admins
        console.print('\n')
        setup_admins()

        console.print('\n[bold green]✓ System setup complete![/bold green]')

    except Exception as e:
        console.print(f'[red]Setup failed: {e}[/red]')
        raise typer.Exit(1)


async def get_custom_fields(entity_type: str) -> List[dict]:
    """Fetch custom fields for a specific entity type from Pipedrive using v1 API"""
    try:
        # Custom fields endpoints are only available in v1 API
        url = f'{settings.pd_base_url}/api/v1/{entity_type}Fields'
        headers = {'Accept': 'application/json'}
        params = {'api_token': settings.pd_api_key}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get('data', [])
    except Exception as e:
        logger.error(f'Failed to fetch custom fields for {entity_type}: {e}')
        raise


def display_field_mappings():
    """Display current field mappings in a table"""
    # Organization fields
    table = Table(title='Organization (Company) Field Mappings')
    table.add_column('Field Name', style='cyan', no_wrap=True)
    table.add_column('Current ID', style='yellow')
    table.add_column('Field Label in Pipedrive', style='green')

    for field_name, field_id in COMPANY_PD_FIELD_MAP.items():
        table.add_row(field_name, field_id, '')

    console.print(table)

    # Deal fields
    table = Table(title='\nDeal Field Mappings')
    table.add_column('Field Name', style='cyan', no_wrap=True)
    table.add_column('Current ID', style='yellow')
    table.add_column('Field Label in Pipedrive', style='green')

    for field_name, field_id in DEAL_PD_FIELD_MAP.items():
        table.add_row(field_name, field_id, '')

    console.print(table)

    # Person fields
    table = Table(title='\nPerson (Contact) Field Mappings')
    table.add_column('Field Name', style='cyan', no_wrap=True)
    table.add_column('Current ID', style='yellow')
    table.add_column('Field Label in Pipedrive', style='green')

    for field_name, field_id in CONTACT_PD_FIELD_MAP.items():
        table.add_row(field_name, field_id, '')

    console.print(table)


def setup_field_mappings():
    """Setup field mappings - core logic extracted for use in setup command"""
    console.print('[bold cyan]Field Mappings Setup[/bold cyan]\n')

    try:
        # Fetch custom fields
        org_fields = asyncio.run(get_custom_fields('organization'))
        deal_fields = asyncio.run(get_custom_fields('deal'))
        person_fields = asyncio.run(get_custom_fields('person'))

        # Build lookup maps
        org_fields_map = {f['key']: {'name': f['name'], 'id': f['key']} for f in org_fields}
        deal_fields_map = {f['key']: {'name': f['name'], 'id': f['key']} for f in deal_fields}
        person_fields_map = {f['key']: {'name': f['name'], 'id': f['key']} for f in person_fields}

        # Display current mappings with field names from Pipedrive
        console.print('[bold]Current Field Mappings:[/bold]\n')

        # Organization fields
        table = Table(title='Organization (Company) Fields')
        table.add_column('Hermes Field', style='cyan', no_wrap=True)
        table.add_column('Pipedrive Name', style='green')
        table.add_column('Field ID', style='yellow')
        table.add_column('Status', style='red')

        for field_name, field_id in _DEFAULT_COMPANY_PD_FIELD_MAP.items():
            pd_field = org_fields_map.get(field_id, {})
            status = '✓' if pd_field else '✗ Not Found'
            table.add_row(field_name, pd_field.get('name', ''), field_id, status)

        console.print(table)

        # Deal fields
        table = Table(title='\nDeal Fields')
        table.add_column('Hermes Field', style='cyan', no_wrap=True)
        table.add_column('Pipedrive Name', style='green')
        table.add_column('Field ID', style='yellow')
        table.add_column('Status', style='red')

        for field_name, field_id in _DEFAULT_DEAL_PD_FIELD_MAP.items():
            pd_field = deal_fields_map.get(field_id, {})
            status = '✓' if pd_field else '✗ Not Found'
            table.add_row(field_name, pd_field.get('name', ''), field_id, status)

        console.print(table)

        # Person fields
        table = Table(title='\nPerson (Contact) Fields')
        table.add_column('Hermes Field', style='cyan', no_wrap=True)
        table.add_column('Pipedrive Name', style='green')
        table.add_column('Field ID', style='yellow')
        table.add_column('Status', style='red')

        for field_name, field_id in _DEFAULT_CONTACT_PD_FIELD_MAP.items():
            pd_field = person_fields_map.get(field_id, {})
            status = '✓' if pd_field else '✗ Not Found'
            table.add_row(field_name, pd_field.get('name', ''), field_id, status)

        console.print(table)

        # Ask if user wants to generate override file
        if not Confirm.ask('\n[cyan]Generate field_mappings_override.py?[/cyan]', default=True):
            return

        # Generate the override file
        override_content = '''"""
Field mappings override file for Hermes.
This file is gitignored and allows local customization of Pipedrive field IDs.

Generated by system_setup.py
"""

# Copy these mappings and update the field IDs to match your Pipedrive instance

COMPANY_PD_FIELD_MAP = {
'''

        for field_name, field_id in _DEFAULT_COMPANY_PD_FIELD_MAP.items():
            pd_field = org_fields_map.get(field_id, {})
            comment = f'  # {pd_field.get("name", "Field not found in Pipedrive")}'
            override_content += f"    '{field_name}': '{field_id}',{comment}\n"

        override_content += """}

DEAL_PD_FIELD_MAP = {
"""

        for field_name, field_id in _DEFAULT_DEAL_PD_FIELD_MAP.items():
            pd_field = deal_fields_map.get(field_id, {})
            comment = f'  # {pd_field.get("name", "Field not found in Pipedrive")}'
            override_content += f"    '{field_name}': '{field_id}',{comment}\n"

        override_content += """}

CONTACT_PD_FIELD_MAP = {
"""

        for field_name, field_id in _DEFAULT_CONTACT_PD_FIELD_MAP.items():
            pd_field = person_fields_map.get(field_id, {})
            comment = f'  # {pd_field.get("name", "Field not found in Pipedrive")}'
            override_content += f"    '{field_name}': '{field_id}',{comment}\n"

        override_content += '}\n'

        # Write the file
        override_path = Path('field_mappings_override.py')
        override_path.write_text(override_content)

        console.print(f'\n[green]✓ Generated {override_path}[/green]')
        console.print('[yellow]Edit this file to update field IDs for your Pipedrive instance.[/yellow]')
        console.print('[yellow]The application will use these mappings on next restart.[/yellow]')

    except Exception as e:
        console.print(f'[red]Failed to generate field mappings: {e}[/red]')
        raise typer.Exit(1)


@app.command()
def fields():
    """Generate field_mappings_override.py from Pipedrive custom fields"""
    setup_field_mappings()


async def get_pipedrive_users() -> List[dict]:
    """Fetch all users from Pipedrive using v1 API"""
    try:
        # Users endpoint is only available in v1 API
        url = f'{settings.pd_base_url}/api/v1/users'
        headers = {'Accept': 'application/json'}
        params = {'api_token': settings.pd_api_key}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get('data', [])
    except Exception as e:
        logger.error(f'Failed to fetch Pipedrive users: {e}')
        raise


def setup_admins():
    """Setup admin users - core logic extracted for use in setup command"""
    console.print('[bold cyan]Admin Setup[/bold cyan]\n')

    db = get_session()

    # Show existing admins
    existing_admins = db.exec(select(Admin)).all()
    if existing_admins:
        console.print('[bold]Existing Admins:[/bold]')
        table = Table()
        table.add_column('ID', style='cyan')
        table.add_column('Name', style='green')
        table.add_column('Email', style='yellow')
        table.add_column('TC2 ID', style='magenta')
        table.add_column('PD ID', style='blue')

        for admin in existing_admins:
            table.add_row(
                str(admin.id),
                f'{admin.first_name} {admin.last_name}',
                admin.username,
                str(admin.tc2_admin_id) if admin.tc2_admin_id else '-',
                str(admin.pd_owner_id) if admin.pd_owner_id else '-',
            )

        console.print(table)
        console.print()

    # Fetch Pipedrive users
    console.print('[cyan]Fetching users from Pipedrive...[/cyan]\n')
    try:
        pd_users = asyncio.run(get_pipedrive_users())
    except Exception as e:
        console.print(f'[red]Failed to fetch Pipedrive users: {e}[/red]')
        db.close()
        raise typer.Exit(1)

    if not pd_users:
        console.print('[red]No users found in Pipedrive![/red]')
        db.close()
        raise typer.Exit(1)

    # Filter out users that already have admin records
    existing_pd_ids = {admin.pd_owner_id for admin in existing_admins if admin.pd_owner_id}
    available_users = [user for user in pd_users if user.get('id') not in existing_pd_ids]

    if not available_users:
        console.print('[yellow]All Pipedrive users already have admin records.[/yellow]')
        if not Confirm.ask('\n[cyan]View all Pipedrive users anyway?[/cyan]', default=False):
            db.close()
            return
        available_users = pd_users

    # Display Pipedrive users
    console.print('[bold]Pipedrive Users:[/bold]')
    table = Table()
    table.add_column('Index', style='cyan', no_wrap=True)
    table.add_column('Name', style='green')
    table.add_column('Email', style='yellow')
    table.add_column('PD ID', style='blue')
    table.add_column('Active', style='white')

    for idx, user in enumerate(available_users, 1):
        table.add_row(
            str(idx),
            user.get('name', ''),
            user.get('email', ''),
            str(user.get('id', '')),
            '✓' if user.get('active_flag') else '✗',
        )

    console.print(table)

    # Ask which users to create admins for
    console.print('\n[bold]Select users to create admin records for:[/bold]')
    console.print('Enter indices separated by commas (e.g., 1,3,5) or "all" for all users')

    selection = Prompt.ask('Selection', default='')

    if not selection:
        console.print('[yellow]No users selected.[/yellow]')
        db.close()
        return

    # Parse selection
    if selection.lower() == 'all':
        selected_users = available_users
    else:
        try:
            indices = [int(i.strip()) for i in selection.split(',')]
            selected_users = [available_users[i - 1] for i in indices if 1 <= i <= len(available_users)]
        except (ValueError, IndexError) as e:
            console.print(f'[red]Invalid selection: {e}[/red]')
            db.close()
            raise typer.Exit(1)

    # Create admin for each selected user
    for user in selected_users:
        console.print(f'\n[bold]Creating admin for: {user.get("name")}[/bold]')

        # Ask for TC2 Admin ID
        tc2_admin_id = IntPrompt.ask('TC2 Admin ID (leave empty to skip)', default=None)

        if tc2_admin_id is None:
            console.print('[yellow]Skipped (no TC2 Admin ID provided)[/yellow]')
            continue

        # Extract name parts
        name = user.get('name', '').strip()
        name_parts = name.split(' ', 1)
        first_name = name_parts[0] if name_parts else 'Unknown'
        last_name = name_parts[1] if len(name_parts) > 1 else ''

        # Create admin with sensible defaults
        try:
            admin = db.create(
                Admin(
                    username=user.get('email', ''),
                    first_name=first_name,
                    last_name=last_name,
                    timezone='Europe/London',  # Default timezone
                    tc2_admin_id=tc2_admin_id,
                    pd_owner_id=user.get('id'),
                    # Assume they are sales and support
                    is_sales_person=True,
                    is_support_person=True,
                    is_bdr_person=False,
                    # Sell all plans
                    sells_payg=True,
                    sells_startup=True,
                    sells_enterprise=True,
                    # Sell to all regions
                    sells_gb=True,
                    sells_us=True,
                    sells_au=True,
                    sells_ca=True,
                    sells_eu=True,
                    sells_row=True,
                )
            )

            console.print(f'[green]✓ Created admin: {admin.first_name} {admin.last_name} (ID: {admin.id})[/green]')
        except Exception as e:
            console.print(f'[red]✗ Failed to create admin: {e}[/red]')

    db.close()
    console.print('\n[bold green]✓ Admin setup complete![/bold green]')


@app.command()
def admins():
    """Create Admin records from Pipedrive users"""
    setup_admins()


if __name__ == '__main__':
    app()
