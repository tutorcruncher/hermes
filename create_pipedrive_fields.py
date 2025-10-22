"""
Script to create custom fields in Pipedrive via API.
"""
import asyncio
import httpx
from app.core.config import settings


# Field type mapping: Hermes type -> Pipedrive field_type
FIELD_TYPE_MAP = {
    'Numerical': 'int',
    'Large text': 'varchar_auto',
    'Text': 'varchar',
    'Date': 'date',
}

ORGANIZATION_FIELDS = [
    {'name': 'hermes_id', 'field_type': 'double'},
    {'name': 'tc2_status', 'field_type': 'text'},
    {'name': 'tc2_cligency_url', 'field_type': 'text'},
    {'name': 'paid_invoice_count', 'field_type': 'double'},
    {'name': 'website', 'field_type': 'text'},
    {'name': 'price_plan', 'field_type': 'text'},
    {'name': 'estimated_income', 'field_type': 'text'},
    {'name': 'support_person_id', 'field_type': 'double'},
    {'name': 'bdr_person_id', 'field_type': 'double'},
    {'name': 'signup_questionnaire', 'field_type': 'text'},
    {'name': 'utm_source', 'field_type': 'text'},
    {'name': 'utm_campaign', 'field_type': 'text'},
    {'name': 'created', 'field_type': 'date'},
    {'name': 'pay0_dt', 'field_type': 'date'},
    {'name': 'pay1_dt', 'field_type': 'date'},
    {'name': 'pay3_dt', 'field_type': 'date'},
    {'name': 'gclid', 'field_type': 'text'},
    {'name': 'gclid_expiry_dt', 'field_type': 'date'},
    {'name': 'email_confirmed_dt', 'field_type': 'date'},
    {'name': 'card_saved_dt', 'field_type': 'date'},
]

PERSON_FIELDS = [
    {'name': 'hermes_id', 'field_type': 'double'},
]

DEAL_FIELDS = [
    {'name': 'hermes_id', 'field_type': 'double'},
    {'name': 'support_person_id', 'field_type': 'double'},
    {'name': 'tc2_cligency_url', 'field_type': 'text'},
    {'name': 'signup_questionnaire', 'field_type': 'text'},
    {'name': 'utm_campaign', 'field_type': 'text'},
    {'name': 'utm_source', 'field_type': 'text'},
    {'name': 'bdr_person_id', 'field_type': 'double'},
    {'name': 'paid_invoice_count', 'field_type': 'double'},
    {'name': 'tc2_status', 'field_type': 'text'},
    {'name': 'website', 'field_type': 'text'},
    {'name': 'price_plan', 'field_type': 'text'},
    {'name': 'estimated_income', 'field_type': 'text'},
]


async def create_field(client: httpx.AsyncClient, entity_type: str, field_data: dict):
    """Create a custom field in Pipedrive."""
    url = f'https://api.pipedrive.com/v1/{entity_type}Fields'

    params = {
        'api_token': settings.pd_api_key,
    }

    payload = {
        'name': field_data['name'],
        'field_type': field_data['field_type'],
    }

    try:
        response = await client.post(url, json=payload, params=params)
        response.raise_for_status()
        result = response.json()

        if result.get('success'):
            field_id = result['data']['key']
            print(f"✓ Created {entity_type} field: {field_data['name']} (ID: {field_id})")
        else:
            print(f"✗ Failed to create {entity_type} field: {field_data['name']} - {result}")

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            error_data = e.response.json()
            if 'already exists' in str(error_data).lower():
                print(f"- {entity_type} field already exists: {field_data['name']}")
            else:
                print(f"✗ Error creating {entity_type} field {field_data['name']}: {error_data}")
        else:
            print(f"✗ HTTP error creating {entity_type} field {field_data['name']}: {e}")
    except Exception as e:
        print(f"✗ Error creating {entity_type} field {field_data['name']}: {e}")

    # Add delay to avoid rate limiting
    await asyncio.sleep(0.5)


async def main():
    """Create all custom fields in Pipedrive."""
    print(f"Creating custom fields in Pipedrive...\n")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Create organization fields
        print("=== Organization Fields ===")
        for field in ORGANIZATION_FIELDS:
            await create_field(client, 'organization', field)

        print("\n=== Person Fields ===")
        for field in PERSON_FIELDS:
            await create_field(client, 'person', field)

        print("\n=== Deal Fields ===")
        for field in DEAL_FIELDS:
            await create_field(client, 'deal', field)

    print("\n✓ Done! Now run: make setup-fields")


if __name__ == '__main__':
    asyncio.run(main())
