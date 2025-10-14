# Hermes - AI Agent Development Guide

This document provides guidelines for AI assistants working on the Hermes codebase to maintain consistency with existing patterns and conventions.

## Table of Contents
- [Project Overview](#project-overview)
- [Code Style](#code-style)
- [Project Structure](#project-structure)
- [Models & Database](#models--database)
- [Testing Patterns](#testing-patterns)
- [API & Webhooks](#api--webhooks)
- [Background Tasks](#background-tasks)
- [Schema & Validation](#schema--validation)
- [Error Handling](#error-handling)
- [Logging](#logging)
- [Common Patterns](#common-patterns)

## Project Overview

Hermes is a sales system that connects TutorCruncher (TC2), the callbooker website, and Pipedrive CRM.

**Tech Stack:**
- FastAPI (web framework)
- Tortoise ORM (async database)
- Pydantic (data validation)
- PostgreSQL (database)
- Redis (caching)
- Logfire (observability)
- Sentry (error tracking)

**Glossary:**
- **Company** = Cligency (TC2) = Organisation (Pipedrive)
- **Contact** = SR (TC2) = Person (Pipedrive)
- **Deal** = Deal (Pipedrive only)
- **Meeting** = Activity (Pipedrive)

## Code Style

### Formatting (Ruff)
```toml
line-length = 120
quote-style = 'single'  # Use single quotes
combine-as-imports = true
```

### Key Conventions
1. **Quotes**: Use single quotes for strings
2. **Line Length**: Maximum 120 characters
3. **Imports**: Combine imports from same module
4. **Type Hints**: Use modern Python type hints (e.g., `str | None` instead of `Optional[str]`)
5. **Docstrings**: Use for complex functions and classes, triple quotes with description
6. **f-strings**: Prefer f-strings over `.format()` or `%` formatting

### Naming Conventions
- **Files**: Snake case (`_utils.py`, `_schema.py`, `_process.py`)
- **Classes**: PascalCase (`Company`, `CustomField`, `PDDeal`)
- **Functions/Variables**: Snake case (`get_config`, `sales_person`, `tc2_admin_id`)
- **Constants**: UPPER_SNAKE_CASE (`STATUS_PENDING`, `TYPE_STR`)
- **Private**: Leading underscore (`_clean_for_pd`, `_slugify`)

## Project Structure

```
app/
├── admin/           # Admin interface (FastAPI-Admin)
├── callbooker/      # Website callbooker integration
├── hermes/          # Core Hermes endpoints
├── pipedrive/       # Pipedrive integration
│   ├── _schema.py   # Pydantic models for Pipedrive
│   ├── _process.py  # Business logic for processing webhooks
│   ├── _utils.py    # Helper utilities
│   ├── api.py       # Pipedrive API client
│   ├── tasks.py     # Background tasks
│   └── views.py     # API endpoints/webhooks
├── tc2/             # TutorCruncher integration (same structure)
├── models.py        # Tortoise ORM models
├── base_schema.py   # Shared Pydantic base classes
├── settings.py      # Configuration/settings
├── utils.py         # Shared utilities
└── main.py          # FastAPI app initialization

tests/
├── conftest.py      # Pytest fixtures
├── _common.py       # Shared test utilities
└── [app]/           # Tests mirror app structure
    ├── test_*.py
    └── helpers.py   # Test helpers
```

### Module Organization Pattern
Each app module follows this structure:
- `views.py`: FastAPI endpoints and webhooks
- `_schema.py`: Pydantic schemas for validation
- `_process.py`: Business logic (processing data)
- `_utils.py`: Helper functions and logger
- `api.py`: External API client functions
- `tasks.py`: Background/async tasks

## Models & Database

### Tortoise ORM Patterns

```python
from tortoise import fields, models

class Company(HermesModel):
    """
    Model docstring explaining what it represents.
    Cross-system mapping in glossary.
    """
    # Constants at top
    STATUS_PENDING = 'pending_email_conf'
    STATUS_TRIAL = 'trial'
    
    # Primary key
    id = fields.IntField(primary_key=True)
    
    # Required fields
    name = fields.CharField(max_length=255)
    
    # Optional fields with null=True
    tc2_agency_id = fields.IntField(unique=True, null=True)
    
    # Foreign keys with related_name
    sales_person = fields.ForeignKeyField(
        'models.Admin', 
        related_name='sales'
    )
    
    # Reverse relations as type hints
    contacts: fields.ReverseRelation['Contact']
    
    # Properties for computed values
    @property
    def pd_org_url(self):
        return f'{settings.pd_base_url}/organization/{self.pd_org_id}/'
    
    # String representation
    def __str__(self):
        return self.name
```

### Key Model Classes
- **HermesModel**: Base for Company, Contact, Deal, Meeting (adds custom field support)
- **models.Model**: Base for Config, CustomField, etc.
- **AbstractAdmin**: Base for Admin (from fastapi-admin)

### Database Operations
```python
# Create
company = await Company.create(name='Test', ...)

# Get single (raises DoesNotExist if not found)
company = await Company.get(id=1)

# Filter
companies = await Company.filter(narc=False)

# With related objects
company = await Company.get(id=1).prefetch_related('contacts')
contacts = await company.contacts  # Already loaded

# Select for update (in transactions)
async with in_transaction():
    company = await Company.select_for_update().get(id=1)
    # ... modify company
    await company.save()

# Update or create
company, created = await Company.update_or_create(
    tc2_agency_id=123,
    defaults={'name': 'New Name'}
)
```

## Testing Patterns

### Test Structure
```python
from tests._common import HermesTestCase
from tests.pipedrive.helpers import FakePipedrive, fake_pd_request

class PipedriveTasksTestCase(HermesTestCase):
    def setUp(self):
        """Synchronous setup (called for each test)"""
        super().setUp()
        self.pipedrive = FakePipedrive()
    
    async def asyncSetUp(self):
        """Async setup (called for each test)"""
        await super().asyncSetUp()
        # Create test data
        self.admin = await Admin.create(...)
        await CustomField.create(...)
        await build_custom_field_schema()
    
    @mock.patch('app.pipedrive.api.session.request')
    async def test_something(self, mock_request):
        """Test description"""
        # Arrange
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Company.create(...)
        
        # Act
        await pd_post_process_client_event(company)
        
        # Assert
        assert self.pipedrive.db['organizations'] == {...}
```

### HermesTestCase Base Class
Located in `tests/_common.py`:
- Inherits from `tortoise.contrib.test.TestCase`
- Sets up async test client
- Creates default Pipeline and Stage
- Configures settings for testing

### Test Helpers
- **FakePipedrive**: Mock Pipedrive API responses
- **fake_pd_request**: Helper for mocking API calls
- Use `@mock.patch` for external dependencies
- Use fixtures in `conftest.py` for shared setup

### Test Naming
- File: `test_[feature].py`
- Class: `[Feature]TestCase`
- Method: `test_[specific_behavior]`
- Be descriptive about what's being tested

## API & Webhooks

### FastAPI Endpoint Pattern
```python
from fastapi import APIRouter, Header, HTTPException
from starlette.background import BackgroundTasks
from starlette.requests import Request

router = APIRouter()

@router.post('/callback/', name='System callback')
async def callback(
    request: Request,
    webhook: WebhookSchema,  # Pydantic schema
    webhook_signature: Optional[str] = Header(None),
    tasks: BackgroundTasks = None  # For background tasks
):
    """
    Webhook endpoint description.
    What it does, what it triggers, etc.
    """
    # 1. Verify signature (if required)
    if not settings.dev_mode:
        expected_sig = hmac.new(...)
        if not compare_digest(webhook_signature, expected_sig):
            raise HTTPException(status_code=403, detail='Unauthorized')
    
    # 2. Process each event
    for event in webhook.events:
        company, deal = await update_from_event(event.subject)
        
        # 3. Queue background tasks
        if company:
            tasks.add_task(pd_post_process_client_event, company, deal)
    
    return {'status': 'ok'}
```

### Router Registration (in `main.py`)
```python
app.include_router(tc2_router, prefix='/tc2')
app.include_router(pipedrive_router, prefix='/pipedrive')
```

### Background Tasks
Use `BackgroundTasks` for operations that should happen after response:
- Syncing to external systems
- Long-running operations
- Non-critical operations

**Important**: Background tasks run AFTER the response is sent, so objects may be deleted/modified before they run.

## Background Tasks

### Task Pattern (in `tasks.py`)
```python
import logfire
from tortoise.exceptions import DoesNotExist

from app.pipedrive._utils import app_logger

async def pd_post_process_client_event(company: Company, deal: Deal = None):
    """
    Called after a client event from TC2. For example, a client paying an invoice.
    """
    with logfire.span('pd_post_process_client_event'):
        try:
            await _transy_get_and_create_or_update_organisation(company)
            for contact in await company.contacts:
                await _transy_get_and_create_or_update_person(contact)
            if deal:
                await _transy_get_and_create_or_update_deal(deal)
                await update_or_create_inherited_deal_custom_field_values(company)
        except DoesNotExist as e:
            app_logger.info(f'Object no longer exists, skipping Pipedrive updates: {e}')
```

### Key Principles
1. **Wrap in logfire span** for observability
2. **Handle DoesNotExist** - objects may be deleted before task runs
3. **Use transactions** when modifying database
4. **Prefix with module** (e.g., `pd_post_`, `tc2_`)
5. **Log info, not errors** for expected failures

### Transaction Pattern
```python
async def _transy_get_and_create_or_update_deal(deal: Deal) -> PDDeal:
    """
    Create or update a Deal in Pipedrive in a transaction
    """
    async with in_transaction():
        deal = await Deal.select_for_update().get(id=deal.id)
        return await get_and_create_or_update_pd_deal(deal)
```

## Schema & Validation

### Pydantic Schema Pattern
```python
from pydantic import Field, field_validator, model_validator
from app.base_schema import HermesBaseModel

class Organisation(PipedriveBaseModel):
    """Pipedrive Organization schema"""
    id: Optional[int] = Field(None, exclude=True)
    name: Optional[str] = None
    owner_id: Optional[int] = ForeignKeyField(None, model=Admin, fk_field_name='pd_owner_id')
    
    # Validator for field transformation
    _get_obj_id = field_validator('owner_id', mode='before')(_get_obj_id)
    
    @classmethod
    async def from_company(cls, company: Company) -> 'Organisation':
        """Create from Hermes Company model"""
        cls_kwargs = dict(
            name=company.name,
            owner_id=(await company.sales_person).pd_owner_id,
            ...
        )
        cls_kwargs.update(await cls.get_custom_field_vals(company))
        final_kwargs = _clean_for_pd(**cls_kwargs)
        return cls(**final_kwargs)
    
    async def company_dict(self, custom_fields: list[CustomField]) -> dict:
        """Convert to dict for creating/updating Company"""
        return _clean_for_pd(
            name=self.name,
            ...
        )
```

### Base Classes
- **HermesBaseModel**: Base for all schemas, includes custom field support
- **PipedriveBaseModel**: Extends HermesBaseModel for Pipedrive schemas

### Common Validators
```python
def _get_obj_id(v) -> str | int:
    """Extract ID from dict or return value directly"""
    if isinstance(v, dict):
        return v['value']
    return v

def _clean_for_pd(**kwargs) -> dict:
    """Clean data for Pipedrive API (remove None, convert datetime to date)"""
    data = {}
    for k, v in kwargs.items():
        if v is None:
            continue
        elif isinstance(v, datetime):
            v = v.date()
        data[k] = v
    return data
```

## Error Handling

### Exception Patterns
```python
from tortoise.exceptions import DoesNotExist
from fastapi import HTTPException

# Database: Use try/except for DoesNotExist
try:
    company = await Company.get(id=1)
except DoesNotExist:
    app_logger.info(f'Company {id} not found')
    # Don't raise - log and continue gracefully

# API: Use HTTPException for client errors
if not authorized:
    raise HTTPException(status_code=403, detail='Unauthorized')

# Background tasks: Catch and log, don't raise
try:
    await external_api_call()
except Exception as e:
    app_logger.error(f'Failed to sync: {e}')
    # Don't raise - task already sent response
```

### When to Raise vs Log
- **Raise**: During request handling, validation, auth
- **Log**: In background tasks, expected failures, cleanup

## Logging

### Logger Setup (in `_utils.py`)
```python
import logging

app_logger = logging.getLogger('hermes.pipedrive')
```

### Logging Patterns
```python
# Info: Normal operations, expected events
app_logger.info(f'Company {company.id} updated successfully')

# Warning: Unexpected but handled
app_logger.warning(f'Duplicate hermes_id {hermes_id} found')

# Error: Actual errors (but still handled)
app_logger.error(f'Failed to create organization: {e}')

# Use f-strings, not old-style formatting
# ❌ app_logger.info('Company %s updated', company.id)
# ✅ app_logger.info(f'Company {company.id} updated')
```

### Logfire Spans
Wrap expensive or important operations:
```python
import logfire

with logfire.span('operation_name'):
    await expensive_operation()
```

## Common Patterns

### Custom Fields
Custom fields sync data between TC2 and Pipedrive:
```python
# Get custom fields for an object type
custom_fields = await CustomField.filter(linked_object_type='Company')

# Get custom field values from Pydantic model
cls_kwargs.update(await cls.get_custom_field_vals(company))

# Process custom field values on save
await company.process_custom_field_vals(old_vals, new_vals)
```

### Async/Await
- Always use `async def` for functions that do I/O
- Always `await` async functions
- Use `async with` for transactions
- Use `async for` for async iterators

### Settings
```python
from app.utils import settings

# Access settings
api_key = settings.pd_api_key
base_url = settings.tc2_base_url

# Development mode check
if settings.dev_mode:
    # Skip auth, etc.
```

### Admin Utilities
```python
from app.utils import get_config, get_redis_client

# Get singleton config
config = await get_config()

# Get Redis client
redis = await get_redis_client()
```

### API Requests Pattern
```python
import httpx

async def get_organization(org_id: int) -> dict:
    """Get organization from Pipedrive"""
    url = f'{settings.pd_base_url}/api/v1/organizations/{org_id}'
    params = {'api_token': settings.pd_api_key}
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()['data']
```

## Development Workflow

### Making Changes
1. **Create/modify code** following patterns above
2. **Run linter**: `ruff check app/` (fixes many issues automatically)
3. **Format code**: `ruff format app/`
4. **Run tests**: `make test` or `pytest tests/[specific_test].py`
5. **Check migrations**: If models changed, run `aerich migrate`
6. **Update this guide** if adding new patterns

### Common Commands
```bash
make install        # Install dependencies
make install-dev    # Install dev dependencies
make test           # Run tests
make reset-db       # Reset database
ruff check app/     # Lint code
ruff format app/    # Format code
```

### Testing Workflow
1. Write test first (TDD when possible)
2. Run specific test: `pytest tests/pipedrive/test_tasks.py::TestClass::test_method -v`
3. Check coverage: `pytest --cov=app tests/`
4. All tests should pass before committing

## Key Differences from Typical Patterns

1. **Single quotes** not double quotes (enforced by ruff)
2. **Modern type hints** (e.g., `str | None` instead of `Optional[str]`)
3. **Background tasks** need DoesNotExist handling
4. **Custom fields** are dynamic - loaded at startup
5. **Three systems** (TC2, Pipedrive, Hermes) must stay in sync
6. **app_logger.info** not `logfire.warn` for expected failures
7. **Always use transactions** when updating related objects

## Anti-Patterns to Avoid

❌ **Don't** use double quotes for strings
❌ **Don't** use `Optional[Type]` - use `Type | None`
❌ **Don't** raise exceptions in background tasks
❌ **Don't** use `.format()` or `%` - use f-strings
❌ **Don't** forget to handle DoesNotExist in tasks
❌ **Don't** use `logfire.warn()` with multiple args - use f-strings
❌ **Don't** create models without `__str__` method
❌ **Don't** forget `related_name` on foreign keys

## Questions or Additions?

When in doubt:
1. Look at existing similar code
2. Check this guide
3. Run the linter
4. Write tests
5. Ask the team

This guide should be updated as new patterns emerge or existing ones evolve.

