# Hermes v4 - AI Agent Development Guide

This document provides guidelines for AI assistants working on the Hermes v4 codebase to maintain consistency with existing patterns and conventions.

## Table of Contents
- [Project Overview](#project-overview)
- [Critical Test Rules](#critical-test-rules)
- [Code Style](#code-style)
- [Project Structure](#project-structure)
- [Models & Database](#models--database)
- [Field Mapping System](#field-mapping-system)
- [API Integration Patterns](#api-integration-patterns)
- [Testing Patterns](#testing-patterns)
- [Common Patterns](#common-patterns)

---

## Project Overview

Hermes is a sales integration system that connects three external systems:
- **TutorCruncher (TC2)** - Internal business management system
- **Pipedrive CRM** - Sales pipeline management
- **Website Callbooker** - Customer-facing booking system

**Tech Stack:**
- FastAPI (web framework)
- SQLModel (async ORM built on SQLAlchemy)
- Pydantic v2 (data validation)
- PostgreSQL (database)
- Logfire (observability)
- Sentry (error tracking)
- Google Calendar API (meeting scheduling)

**Glossary:**
- **Company** = Cligency (TC2) = Organisation (Pipedrive)
- **Contact** = SR (TC2) = Person (Pipedrive)
- **Deal** = Deal (Pipedrive only)
- **Meeting** = Activity (Pipedrive)

**Data Flow:**
- TC2 → Hermes → Pipedrive ✅
- Callbooker → Hermes → Pipedrive ✅
- Pipedrive → Hermes (NO TC2 sync) ✅

---

## Critical Test Rules

### 0. End-to-End Testing Philosophy

**All tests must start with an HTTP request or a background task call.**

#### ✅ Good - Testing through webhooks
```python
async def test_tc2_webhook_creates_company(client, db):
    """Test that TC2 webhook creates company"""
    webhook_data = {...}
    
    r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
    
    assert r.status_code == 200
    
    # Verify company was created
    company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).first()
    assert company is not None
```

#### ✅ Good - Testing background tasks directly
```python
@patch('app.pipedrive.api.pipedrive_request')
async def test_sync_company_task(mock_api, db, test_company):
    """Test sync task"""
    mock_api.return_value = {'data': {'id': 999}}
    
    await sync_company_to_pipedrive(test_company.id)
    
    assert mock_api.called
```

#### ❌ Bad - Testing internal functions directly
```python
async def test_process_organisation(db, test_company):
    """Test process_organisation function"""
    org_data = Organisation(...)
    
    # ❌ Don't call internal functions directly
    company = await process_organisation(org_data, None, db)
    
    assert company is not None
```

#### ❌ Bad - Testing Pydantic models directly
```python
def test_model_validation():
    """Test model validation"""
    # ❌ Don't instantiate models directly for testing
    event = CBSalesCall(...)
    assert event.first_name == 'Test'
```

**Why?** End-to-end tests ensure the entire flow works (request → validation → processing → response), not just isolated functions.

**Exception:** Model property tests (`__str__`, computed properties) and pure helper functions can be tested directly.

### 1. URL Generation Rules

**ALWAYS use `client.app.url_path_for()` for URL references in tests.**

#### ✅ Good - Using url_path_for
```python
def test_tc2_callback(client, db):
    r = client.post(
        client.app.url_path_for('tc2-callback'),
        json=webhook_data
    )
    assert r.status_code == 200
```

#### ❌ Bad - Hardcoded URLs
```python
def test_tc2_callback(client, db):
    r = client.post('/tc2/callback/', json=webhook_data)  # ❌ Hardcoded
    assert r.status_code == 200
```

### 2. Test Data Creation Rules

**Always use `db.create()` instead of `add`, `commit`, and `refresh`.**

#### ✅ Good - Using db.create()
```python
def test_create_company(db, test_admin):
    company = db.create(Company(
        name='Test Company',
        sales_person_id=test_admin.id,
        price_plan='payg',
        country='GB',
    ))
    
    assert company.id is not None
    assert company.name == 'Test Company'
```

#### ❌ Bad - Manual add, commit, refresh
```python
def test_create_company(db, test_admin):
    company = Company(name='Test Company', sales_person_id=test_admin.id)
    db.add(company)  # ❌
    db.commit()      # ❌
    db.refresh(company)  # ❌
```

### 3. Test Response Structure Rules

**Always check the entire response structure, not just individual keys.**

#### ✅ Good - Complete structure check
```python
def test_choose_sales_person(client, test_admin):
    r = client.get(
        client.app.url_path_for('choose-sales-person'),
        params={'plan': 'payg', 'country_code': 'GB'}
    )
    
    assert r.status_code == 200
    assert r.json() == {
        'id': test_admin.id,
        'first_name': 'Test',
        'last_name': 'Admin',
        'email': 'test@example.com',
        'tc2_admin_id': 1,
        'pd_owner_id': 1,
    }
```

#### ❌ Bad - Checking only individual keys
```python
def test_choose_sales_person(client, test_admin):
    r = client.get(...)
    data = r.json()
    assert data['first_name'] == 'Test'  # ❌ Only checking one field
```

### 4. Test Code Style Rules

#### Use `r` for Response Variables
Always use `r` instead of `response` when calling client methods in tests.

#### ✅ Good - Using r for response
```python
def test_endpoint(client):
    r = client.get(client.app.url_path_for('endpoint'))
    assert r.status_code == 200
    assert r.json() == {'status': 'ok'}
```

#### ❌ Bad - Using response
```python
def test_endpoint(client):
    response = client.get(client.app.url_path_for('endpoint'))  # ❌ Use r instead
    assert response.status_code == 200
```

#### Use Inline select() Statements
Don't create intermediate `statement` variables for simple queries. Use inline `select()` calls.

#### ✅ Good - Inline select
```python
def test_get_company(db):
    company = db.exec(select(Company)).first()
    assert company.name == 'Test'
    
    # With where clause
    contact = db.exec(select(Contact).where(Contact.email == 'test@example.com')).first()
    assert contact is not None
```

#### ❌ Bad - Intermediate statement variable
```python
def test_get_company(db):
    statement = select(Company)  # ❌ Unnecessary variable
    company = db.exec(statement).first()
    assert company.name == 'Test'
```

#### No Comments Except Docstrings
Tests should have NO inline comments unless absolutely necessary for complex logic.

#### ✅ Good - Clean test with only docstring
```python
def test_process_tc_client_creates_company(db, test_admin, sample_tc_client_data):
    """Test that processing TC2 client creates a company in Hermes"""
    tc_client = TCClient(**sample_tc_client_data)
    company = await process_tc_client(tc_client, db)
    
    assert company is not None
    assert company.name == 'Test Agency'
```

#### ❌ Bad - Unnecessary comments
```python
def test_process_tc_client_creates_company(db, test_admin, sample_tc_client_data):
    tc_client = TCClient(**sample_tc_client_data)  # ❌ Create client
    company = await process_tc_client(tc_client, db)  # ❌ Process client
    
    assert company is not None  # ❌ Check company exists
```

### 5. Mocking Patterns

**Always use `@patch` decorator instead of inline `with patch()` blocks.**

**For async functions, use `new_callable=AsyncMock` when patching.**

**Use MockResponse object for consistent HTTP response mocking:**

#### ✅ Good - Testing request functions with MockResponse
```python
from tests.helpers import MockResponse, create_mock_response, create_error_response

@patch('httpx.AsyncClient.request')
async def test_api_request(mock_request):
    """Test API request function with MockResponse"""
    mock_response = create_mock_response({'data': {'id': 999}})
    mock_request.return_value = mock_response
    
    result = await pipedrive_request('organizations')
    assert result['data']['id'] == 999
```

#### ✅ Good - Testing higher-level functions by patching internal request
```python
@patch('app.pipedrive.api.pipedrive_request')
async def test_sync_company(mock_request, db, test_company):
    """Test sync function by mocking internal request function"""
    mock_request.return_value = {'data': {'id': 999}}
    await sync_company_to_pipedrive(test_company.id)
```

#### ✅ Good - Using AsyncMock for async functions
```python
from unittest.mock import AsyncMock

@patch('app.pipedrive.tasks.api.get_person', new_callable=AsyncMock)
async def test_sync_person(mock_get, db, test_contact):
    """Test sync function with async mock"""
    mock_get.return_value = {'data': {'id': 999}}
    await sync_person_to_pipedrive(test_contact.id)
```

#### ❌ Bad - Patching entire client class
```python
@patch('httpx.AsyncClient')  # ❌ Don't patch entire class
async def test_api_call(mock_client_class):
    ...
```

#### ❌ Bad - Inline with patch()
```python
async def test_sync_company(db, test_company):
    with patch('app.pipedrive.api.pipedrive_request') as mock_api:  # ❌ Inline
        mock_api.return_value = {'data': {'id': 999}}
        await sync_company_to_pipedrive(test_company.id)
```

#### ❌ Bad - Inline with patch() even for async
```python
async def test_sync_person(db, test_contact):
    with patch('app.pipedrive.tasks.api.get_person', new_callable=AsyncMock) as mock_get:  # ❌ Inline
        mock_get.return_value = {'data': {'id': 999}}
        await sync_person_to_pipedrive(test_contact.id)
```

### 6. Coverage Requirements

**Maintain test coverage above 95% for the entire application.**

```bash
uv run pytest --cov=app --cov-report=term-missing
```

**Coverage Targets:**
- Overall: Minimum 95%
- Critical paths: 100% (webhooks, sync tasks, booking logic)
- API endpoints: 100%
- Business logic: 100%

---

## Code Style

### Formatting (Ruff)
```toml
line-length = 120
quote-style = 'single'  # Single quotes for strings
combine-as-imports = true
```

### Key Conventions
1. **Quotes**: Use single quotes for strings, double quotes for docstrings
2. **Line Length**: Maximum 120 characters
3. **Imports**: Combine imports from same module, module-level only
4. **Type Hints**: Modern Python type hints (e.g., `str | None` instead of `Optional[str]`)
5. **Docstrings**: Use for all functions and classes, triple double-quotes
6. **f-strings**: Prefer f-strings over `.format()` or `%` formatting

### Naming Conventions
- **Files**: Snake case (`models.py`, `field_mappings.py`, `process.py`)
- **Classes**: PascalCase (`Company`, `Organisation`, `TCClient`)
- **Functions/Variables**: Snake case (`get_config`, `sales_person`, `tc2_admin_id`)
- **Constants**: UPPER_SNAKE_CASE (`PP_PAYG`, `TYPE_SALES`) or mapping dicts (`COMPANY_PD_FIELD_MAP`)
- **Private**: Leading underscore (`_company_to_org_data`)

---

## Project Structure

```
v4/
├── app/
│   ├── main_app/           # Core Hermes application
│   │   ├── models.py       # SQLModel database models
│   │   └── views.py        # Core endpoints (round-robin, search)
│   ├── pipedrive/          # Pipedrive CRM integration
│   │   ├── models.py       # Pydantic webhook schemas
│   │   ├── field_mappings.py  # Single source of truth for field IDs
│   │   ├── api.py          # Pipedrive API v2 client
│   │   ├── tasks.py        # Background sync tasks
│   │   ├── process.py      # Webhook processing
│   │   └── views.py        # Webhook endpoint
│   ├── tc2/                # TutorCruncher integration
│   │   ├── models.py       # Pydantic webhook schemas
│   │   ├── api.py          # TC2 API client
│   │   ├── process.py      # Data processing
│   │   └── views.py        # Webhook endpoint
│   ├── callbooker/         # Website callbooker
│   │   ├── models.py       # Request schemas
│   │   ├── views.py        # Booking endpoints
│   │   ├── process.py      # Booking logic
│   │   ├── availability.py # Slot calculation
│   │   ├── google.py       # Google Calendar
│   │   ├── meeting_templates.py
│   │   └── utils.py
│   ├── core/               # Infrastructure
│   │   ├── config.py       # Settings
│   │   ├── database.py     # SQLModel setup
│   │   └── logging.py      # Logging config
│   ├── common/             # Shared utilities
│   │   ├── utils.py
│   │   └── api/errors.py
│   └── main.py             # FastAPI application
├── tests/
│   ├── conftest.py         # Pytest fixtures
│   ├── tc2/
│   ├── pipedrive/
│   └── callbooker/
└── migrations/             # Alembic migrations
```

### Module Organization Pattern
- **`models.py`** in main_app = SQLModel database models (ORM)
- **`models.py`** in integrations = Pydantic validation models (API)
- **`views.py`** = FastAPI endpoints
- **`process.py`** = Business logic
- **`api.py`** = External API client
- **`tasks.py`** = Background sync tasks

---

## Models & Database

### SQLModel Patterns

```python
from datetime import datetime, timezone
from typing import ClassVar, List, Optional
from sqlmodel import Field, Relationship, SQLModel

class Company(SQLModel, table=True):
    """
    Model docstring explaining what it represents.
    """
    # Constants as ClassVar (not database fields)
    STATUS_PENDING: ClassVar[str] = 'pending_email_conf'
    PP_PAYG: ClassVar[str] = 'payg'
    
    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)
    
    # Required fields
    name: str = Field(max_length=255)
    
    # Optional fields
    tc2_agency_id: Optional[int] = Field(default=None, unique=True, index=True)
    
    # Dates - use timezone-aware defaults
    created: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Foreign keys
    sales_person_id: int = Field(foreign_key='admin.id')
    
    # Relationships
    sales_person: 'Admin' = Relationship(back_populates='sales_companies')
    contacts: List['Contact'] = Relationship(back_populates='company')
    
    # Properties for computed values
    @property
    def pd_org_url(self):
        if self.pd_org_id:
            return f'{settings.pd_base_url}/organization/{self.pd_org_id}/'
        return None
    
    # String representation
    def __str__(self):
        return self.name
```

### Key Model Classes
- **Admin** - Sales/support/BDR personnel
- **Company** - Organizations (has 29 fields including Pipedrive mappings)
- **Contact** - Individual contacts
- **Deal** - Sales deals (has all Company fields for Pipedrive)
- **Meeting** - Sales/support meetings
- **Pipeline & Stage** - Pipedrive tracking
- **Config** - Application settings

### Database Operations
```python
from sqlmodel import select

# Create using db.create()
company = db.create(Company(name='Test', ...))

# Get single
company = db.get(Company, company_id)

# Filter with select
statement = select(Company).where(Company.narc == False)
companies = db.exec(statement).all()

# Get first
company = db.exec(statement).first()

# With relationships (use selectinload for eager loading)
from sqlalchemy.orm import selectinload

statement = select(Company).options(selectinload(Company.contacts))
company = db.exec(statement).first()
```

---

## Field Mapping System

**This is unique to Hermes v4** - eliminates CustomField/CustomFieldValue tables!

### The Pattern

**Step 1:** Define mapping once in `pipedrive/field_mappings.py`

```python
COMPANY_PD_FIELD_MAP = {
    'paid_invoice_count': '70527310be44839c869854b055788a69ecbbab66',
    'tc2_status': '57170eb130b8fa45925381623c86011e4e598e21',
    # ... all field name → Pipedrive field ID mappings
}
```

**Step 2:** Reference in Pydantic models (for incoming webhooks)

```python
from app.pipedrive.field_mappings import COMPANY_PD_FIELD_MAP

class Organisation(BaseModel):
    # Standard fields
    id: Optional[int] = None
    name: Optional[str] = None
    
    # Custom fields - reference the mapping
    paid_invoice_count: Optional[int] = Field(
        default=0,
        validation_alias=COMPANY_PD_FIELD_MAP['paid_invoice_count']
    )
```

**Step 3:** Use in sync tasks (for outgoing to Pipedrive)

```python
from app.pipedrive.field_mappings import COMPANY_PD_FIELD_MAP

def _company_to_org_data(company: Company) -> dict:
    custom_fields = {}
    for field_name, pd_field_id in COMPANY_PD_FIELD_MAP.items():
        value = getattr(company, field_name, None)
        if value is not None:
            custom_fields[pd_field_id] = value
    return {'custom_fields': custom_fields, ...}
```

**Benefits:**
- Single source of truth
- Add new field in one place, works everywhere
- No CustomField tables needed
- Type-safe and maintainable

---

## API Integration Patterns

### Pipedrive API v2 Client

**Key differences from v1:**
- Bearer token auth (not query param)
- `/v2/` endpoint prefix
- PATCH for updates (not PUT)
- Only send changed fields

```python
from app.pipedrive import api

# Create
result = await api.create_organisation(org_data)

# Update with PATCH (only changed fields)
old_data = await api.get_organisation(org_id)
new_data = _company_to_org_data(company)
changed_fields = api.get_changed_fields(old_data, new_data)

if changed_fields:
    await api.update_organisation(org_id, changed_fields)

# Delete
await api.delete_organisation(org_id)

# Search
results = await api.search_organisations(term='Test', fields=['name'])
```

### TC2 API Client

```python
from app.tc2 import api

# Get client
client_data = await api.get_client(tc2_cligency_id)

# Update client
await api.update_client(tc2_cligency_id, data={'status': 'active'})
```

### Background Tasks Pattern

```python
from fastapi import BackgroundTasks

@router.post('/callback/')
async def webhook(event: WebhookData, background_tasks: BackgroundTasks):
    # Process event immediately
    company = await process_event(event)
    
    # Queue background task
    background_tasks.add_task(sync_company_to_pipedrive, company.id)
    
    return {'status': 'ok'}
```

**Important:** Background tasks run AFTER the response is sent, so pass IDs not objects.

---

## Testing Patterns

### Test Structure

```python
from unittest.mock import patch

import pytest

from app.main_app.models import Company


class TestTC2Integration:
    """Test TC2 webhook processing"""
    
    @patch('app.pipedrive.api.pipedrive_request')
    async def test_tc2_webhook_creates_company(self, mock_api, client, db, test_admin):
        """Test that TC2 webhook creates company and syncs to Pipedrive"""
        mock_api.return_value = {'data': {'id': 999}}
        
        webhook_data = {
            'events': [{
                'action': 'UPDATE',
                'verb': 'update',
                'subject': {
                    'model': 'Client',
                    'id': 123,
                    'meta_agency': {...},
                    # ... full client data
                }
            }],
            '_request_time': 1234567890,
        }
        
        r = client.post(
            client.app.url_path_for('tc2-callback'),
            json=webhook_data
        )
        
        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}
        
        # Verify company was created
        from sqlmodel import select
        
        statement = select(Company).where(Company.tc2_cligency_id == 123)
        company = db.exec(statement).first()
        
        assert company is not None
        assert company.name == 'Test Agency'
```

### Test Fixtures

Located in `tests/conftest.py`:

```python
@pytest.fixture
def test_admin(db):
    """Create a test admin"""
    return db.create(Admin(
        first_name='Test',
        last_name='Admin',
        username='test@example.com',
        tc2_admin_id=1,
        pd_owner_id=1,
        is_sales_person=True,
    ))
```

**Important:** Use `db.create()` not manual add/commit/refresh!

### Test Data Patterns

```python
@pytest.fixture
def sample_tc_client_data():
    """Sample TC2 client data"""
    return {
        'id': 123,
        'meta_agency': {
            'id': 456,
            'name': 'Test Agency',
            # ... all required fields
        },
        # ... rest of structure
    }
```

### Testing Database Operations

```python
async def test_company_creation(db, test_admin):
    """Test creating a company"""
    company = db.create(Company(
        name='Test',
        sales_person_id=test_admin.id,
        price_plan='payg',
    ))
    
    assert company.id is not None
    assert company.sales_person_id == test_admin.id
```

---

## Common Patterns

### Settings
```python
from app.core.config import settings

# Access settings
api_key = settings.pd_api_key
base_url = settings.tc2_base_url

# Development mode check
if settings.dev_mode:
    # Skip auth, etc.
```

### Database Session
```python
from app.core.database import DBSession, get_db
from fastapi import Depends

@router.post('/endpoint/')
async def endpoint(db: DBSession = Depends(get_db)):
    company = db.get(Company, company_id)
    # ... work with db
```

### Error Handling

```python
from app.common.api.errors import HTTP403, HTTP404

# In endpoints
if not authorized:
    raise HTTP403('Unauthorized')

if not found:
    raise HTTP404('Company not found')

# In background tasks - log, don't raise
try:
    await external_api_call()
except Exception as e:
    logger.error(f'Failed to sync: {e}', exc_info=True)
    # Don't raise - task already sent response
```

### Logging

```python
import logging

logger = logging.getLogger('hermes.pipedrive')

# Info: Normal operations
logger.info(f'Company {company.id} updated successfully')

# Warning: Unexpected but handled
logger.warning(f'Duplicate hermes_id {hermes_id} found')

# Error: Actual errors
logger.error(f'Failed to create organization: {e}', exc_info=True)

# Use f-strings, not old-style formatting
```

### Logfire Spans

Wrap important operations:

```python
import logfire

with logfire.span('operation_name'):
    await expensive_operation()
```

---

## API & Webhooks

### FastAPI Endpoint Pattern

```python
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlmodel import select

from app.core.database import DBSession, get_db

router = APIRouter()

@router.post('/callback/', name='system-callback')
async def callback(
    webhook: WebhookSchema,
    background_tasks: BackgroundTasks,
    db: DBSession = Depends(get_db)
):
    """
    Webhook endpoint description.
    """
    # Process each event
    for event in webhook.events:
        company = await process_event(event, db)
        
        # Queue background tasks (pass IDs not objects!)
        if company:
            background_tasks.add_task(sync_to_external, company.id)
    
    return {'status': 'ok'}
```

### Router Registration (in `main.py`)

```python
from app.tc2.views import router as tc2_router

app.include_router(tc2_router, prefix='/tc2', tags=['tc2'])
```

---

## Async/Await

- Always use `async def` for functions that do I/O
- Always `await` async functions
- Use `async for` for async iterators
- Use `async with` for async context managers

---

## Development Workflow

### Making Changes
1. **Create/modify code** following patterns above
2. **Run linter**: `make lint` or `uv run ruff check app/`
3. **Format code**: `make format` or `uv run ruff format app/`
4. **Run tests**: `make test` or `uv run pytest tests/`
5. **Check migrations**: If models changed, run `make migrate-create msg="..."`

### Common Commands
```bash
make install-dev    # Install dependencies
make test           # Run tests
make test-cov       # Run tests with coverage
make lint           # Check code quality
make format         # Format code
make run            # Run application
make migrate        # Apply migrations
make reset-db       # Reset database
```

### Testing Workflow
1. Write test first (TDD when possible)
2. Run specific test: `uv run pytest tests/tc2/test_tc2_integration.py::TestClass::test_method -v`
3. Check coverage: `uv run pytest --cov=app --cov-report=html`
4. All tests should pass before committing

---

## Key Differences from Typical Patterns

1. **Single quotes** for strings (not double)
2. **Double quotes** for docstrings
3. **Modern type hints** (`str | None` not `Optional[str]`)
4. **Background tasks** use IDs (objects may be deleted)
5. **Field mapping** instead of CustomFields
6. **PATCH not PUT** for Pipedrive updates
7. **One-way Pipedrive sync** (doesn't propagate to TC2)
8. **Three systems** (TC2, Pipedrive, Hermes) must stay in sync
9. **ClassVar** for model constants
10. **No `serialization_alias` on SQLModel** (Pydantic only)

---

## Anti-Patterns to Avoid

❌ **Don't** use double quotes for strings (except docstrings)  
❌ **Don't** use `Optional[Type]` - use `Type | None`  
❌ **Don't** raise exceptions in background tasks  
❌ **Don't** use `.format()` or `%` - use f-strings  
❌ **Don't** use `datetime.utcnow()` - use `datetime.now(timezone.utc)`  
❌ **Don't** use `class Config:` - use `model_config = ConfigDict(...)`  
❌ **Don't** use `@app.on_event()` - use `lifespan` context manager  
❌ **Don't** create models without `__str__` method  
❌ **Don't** forget `related_name` on foreign keys  
❌ **Don't** put `serialization_alias` on SQLModel Field() (Pydantic only!)  
❌ **Don't** use local/in-function imports  
❌ **Don't** compare booleans with `== True` (use `if field:`)  
❌ **Don't** use magic strings for Pipedrive field IDs (use `COMPANY_PD_FIELD_MAP['field_name']`)  

---

## Testing Best Practices

### Always Use
✅ `client.app.url_path_for('route-name')` for URLs  
✅ `db.create(Model(...))` for test data  
✅ `@patch` decorator (not inline)  
✅ Check complete response structures  
✅ Module-level imports only  
✅ Docstrings (no inline comments)  
✅ Async test functions for async code  

### Never Use
❌ Hardcoded URLs in tests  
❌ `db.add()`, `db.commit()`, `db.refresh()` separately  
❌ Inline `with patch()` blocks (use `@patch` decorator)  
❌ Checking only individual response keys  
❌ Inline comments (except for complex logic)  
❌ Explicit IDs when creating test objects  

---

## Examples

### Good Test Example

```python
@patch('app.pipedrive.api.pipedrive_request')
async def test_sync_company_to_pipedrive(self, mock_api, client, db, test_admin):
    """Test that company syncs to Pipedrive with correct field mapping"""
    mock_api.return_value = {'data': {'id': 999}}
    
    company = db.create(Company(
        name='Test Company',
        sales_person_id=test_admin.id,
        price_plan='payg',
        paid_invoice_count=5,
    ))
    
    await sync_company_to_pipedrive(company.id)
    
    assert mock_api.called
    call_data = mock_api.call_args.kwargs['data']
    assert call_data['custom_fields'][COMPANY_PD_FIELD_MAP['paid_invoice_count']] == 5
```

### Good Endpoint Example

```python
from fastapi import APIRouter, Depends
from sqlmodel import select

from app.core.database import DBSession, get_db
from app.main_app.models import Company

router = APIRouter()

@router.get('/companies/', name='get-companies')
async def get_companies(
    name: str | None = None,
    country: str | None = None,
    db: DBSession = Depends(get_db)
):
    """Get companies by filter parameters"""
    statement = select(Company)
    
    if name:
        statement = statement.where(Company.name.ilike(f'%{name}%'))
    if country:
        statement = statement.where(Company.country == country)
    
    companies = db.exec(statement.limit(10)).all()
    
    return [{'id': c.id, 'name': c.name, 'country': c.country} for c in companies]
```

---

## Important Notes

### Field Mapping is Critical
When adding a new Pipedrive custom field:

1. Add to `pipedrive/field_mappings.py` mapping dict
2. Add to SQLModel in `main_app/models.py`
3. Add to Pydantic model in `pipedrive/models.py` with `validation_alias=MAPPING['field']`
4. That's it! Sync logic automatically picks it up.

### Sync Directions Matter
- **TC2 → Hermes → Pipedrive** ✅ Full propagation
- **Callbooker → Hermes → Pipedrive** ✅ Full propagation
- **Pipedrive → Hermes** ✅ Update Hermes ONLY (no TC2 sync)

This prevents circular updates!

### Background Tasks
Always pass IDs to background tasks, not model instances:

```python
# ✅ Good
background_tasks.add_task(sync_company, company.id)

# ❌ Bad
background_tasks.add_task(sync_company, company)  # Object may be deleted!
```

---

## Questions or Additions?

When in doubt:
1. Look at existing similar code
2. Check this guide
3. Check tc-ai-backend AGENTS.md for general FastAPI patterns
4. Run the linter
5. Write tests
6. Ask the team

This guide should be updated as new patterns emerge or existing ones evolve.

---

## Quick Reference

### Import Patterns
```python
# Database models
from app.main_app.models import Admin, Company, Contact, Deal

# API validation models  
from app.pipedrive.models import Organisation, Person, PDDeal
from app.tc2.models import TCClient, TCWebhook
from app.callbooker.models import CBSalesCall

# Field mappings
from app.pipedrive.field_mappings import COMPANY_PD_FIELD_MAP

# API clients
from app.pipedrive import api
from app.tc2 import api

# Utilities
from app.common.utils import sign_args, get_bearer
from app.common.api.errors import HTTP403, HTTP404
from app.core.config import settings
from app.core.database import get_db, get_session
```

### Route Naming
Use kebab-case for route names:
- `'tc2-callback'`
- `'book-sales-call'`
- `'choose-sales-person'`
- `'get-companies'`

---

This guide ensures consistency, maintainability, and quality across the Hermes v4 codebase.


