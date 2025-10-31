# Hermes

![hermes_v2_favicon (1)](https://github.com/tutorcruncher/hermes/assets/70067036/2019e4cf-056e-4e85-9694-5fa0b76dd2a4)

Sales integration system connecting TutorCruncher (TC2), Pipedrive CRM, and the Website Callbooker.

## Overview

Hermes synchronizes customer data between three systems:
- **TutorCruncher (TC2)** - Internal business management system
- **Pipedrive** - CRM for sales pipeline management  
- **Website Callbooker** - Customer-facing meeting booking system

**Data Flow:**
- TC2 → Hermes → Pipedrive
- Callbooker → Hermes → Pipedrive
- Pipedrive → Hermes (updates Hermes only, doesn't sync back to TC2)

## Glossary  
  
Objects are named differently depending on the system:  
  
| Hermes   | TutorCruncher | Pipedrive    | Description                                                       |  
|----------|---------------|--------------|-------------------------------------------------------------------|  
| Company  | Cligency      | Organisation | A business that is a potential/current customer of TutorCruncher |  
| Contact  | SR            | Person       | Someone who works for the Company                                |  
| Deal     |               | Deal         | A potential sale with a Company                                  |  
| Meeting  |               | Activity     | A meeting with a Contact                                         |
| Pipeline |               | Pipeline     | The sales pipelines in Pipedrive                                 |  
| Stage    |               | Stage        | The stages within each pipeline                                  |  

## Tech Stack

- **Language**: Python 3.12+
- **Framework**: FastAPI
- **Database**: PostgreSQL
- **ORM**: SQLModel (async SQLAlchemy + Pydantic)
- **Validation**: Pydantic
- **Migrations**: Alembic
- **Observability**: Logfire
- **Error Tracking**: Sentry
- **External APIs**: TC2, Pipedrive, Google Calendar

## Project Structure

```
hermes/
├── app/
│   ├── main_app/           # Core Hermes models and views
│   │   ├── models.py       # Database models (Company, Contact, Deal, etc.)
│   │   └── views.py        # Core API endpoints
│   ├── pipedrive/          # Pipedrive CRM integration
│   │   ├── models.py       # Pydantic models for webhooks
│   │   ├── field_mappings.py  # Field ID mappings
│   │   ├── api.py          # Pipedrive API client
│   │   ├── tasks.py        # Background sync tasks
│   │   ├── process.py      # Webhook processing logic
│   │   └── views.py        # Webhook endpoints
│   ├── tc2/                # TutorCruncher integration
│   │   ├── models.py       # TC2 webhook schemas
│   │   ├── api.py          # TC2 API client
│   │   ├── process.py      # TC2 data processing
│   │   └── views.py        # TC2 webhook endpoints
│   ├── callbooker/         # Website callbooker integration
│   │   ├── models.py       # Booking request schemas
│   │   ├── views.py        # Booking endpoints
│   │   ├── process.py      # Booking logic
│   │   ├── availability.py # Slot calculation
│   │   └── google.py       # Google Calendar integration
│   ├── core/               # Core infrastructure
│   │   ├── config.py       # Settings and configuration
│   │   ├── database.py     # Database setup
│   │   └── logging.py      # Logging configuration
│   └── main.py             # FastAPI application entry point
├── tests/                  # Test suite
├── migrations/             # Alembic database migrations
├── system_setup.py         # Automated setup script
└── pyproject.toml          # Dependencies and configuration
```

## Getting Started

### Prerequisites

- Python 3.12+
- PostgreSQL
- Access to:
  - TutorCruncher (TC2) instance
  - Pipedrive account
  - Google Cloud project (for calendar integration)

### Installation

1. **Clone and install dependencies:**
```bash
git clone https://github.com/tutorcruncher/hermes.git
cd hermes
make install-dev
```

2. **Create database:**
```bash
make reset-db
```

3. **Configure environment:**
Create a `.env` file in the project root:

```bash
PD_API_KEY=your_pipedrive_api_key
TC2_API_KEY=your_tc2_api_key
G_PRIVATE_KEY_ID=your-key-id
G_PRIVATE_KEY=your-private-key
LOGFIRE_TOKEN=your-logfire-token
```

## Configuration

### 1. TutorCruncher Setup

#### Configure TC2 to send webhooks:
1. In TC2, navigate to Settings > API Integrations
2. Create a new integration named "Hermes"
3. Set URL to `http://localhost:8000/tc2/callback/` (or your ngrok URL)
4. Copy the generated API key and set it as `TC2_API_KEY` in your `.env`

#### Create TC2 Admin users:
Create admin users for different roles:
- PAYG/Startup sales person
- Enterprise sales person  
- BDR (Business Development Representative)
- Support staff (1-2 people)

Note their TC2 admin IDs - you'll need them when creating Hermes Admin records.

### 2. Pipedrive Setup

#### Get API Key:
1. In Pipedrive, go to Settings > Personal Preferences > API
2. Copy your API key and set it as `PD_API_KEY` in your `.env`

#### Create Webhooks:
1. Navigate to Settings > Tools and Apps > Webhooks
2. Create a new webhook:
   - Event action: `*` (all)
   - Event object: `*` (all)
   - Endpoint URL: `http://localhost:8000/pipedrive/callback/` (or your ngrok URL)
   - HTTP Auth: None

#### Create Pipedrive Users:
Create users for each role:
- PAYG/Startup sales
- Enterprise sales
- BDR
- Support (optional)

To get each user's Pipedrive Owner ID:
1. Go to Settings > Manage users
2. Click on a user
3. Copy the number from the end of the URL (e.g., `123456789`)

### 3. Automated Configuration

#### Configure Pipelines and Stages:
```bash
make setup
```

This interactive command will:
- Fetch all pipelines and stages from your Pipedrive account
- Let you select the default entry stage for each pipeline
- Configure which pipelines to use for PAYG, Startup, and Enterprise clients
- Store the configuration in the database

#### Configure Field Mappings:
```bash
make setup-fields
```

This command will:
- Fetch all custom fields from your Pipedrive account
- Show which fields exist and which need to be created
- Generate a `field_mappings_override.py` file with your field IDs

#### Create Custom Fields in Pipedrive:

If `make setup-fields` shows missing fields, create them in Pipedrive:

**Organization Fields:**

| Field Name | Type | Description |
|------------|------|-------------|
| hermes_id | Numerical | Internal Hermes ID |
| tc2_status | Large text | TC2 status |
| tc2_cligency_url | Large text | Link to TC2 client |
| paid_invoice_count | Numerical | Number of paid invoices |
| website | Large text | Company website |
| price_plan | Large text | Plan: payg/startup/enterprise |
| estimated_income | Large text | Estimated monthly income |
| support_person_id | Numerical | Support person PD ID |
| bdr_person_id | Numerical | BDR person PD ID |
| signup_questionnaire | Large text | Signup responses |
| utm_source | Large text | UTM source |
| utm_campaign | Large text | UTM campaign |
| created | Date | Date created |
| pay0_dt | Date | First payment date |
| pay1_dt | Date | Second payment date |
| pay3_dt | Date | Third payment date |
| gclid | Large text | Google Click ID |
| gclid_expiry_dt | Date | GCLID expiry date |
| email_confirmed_dt | Date | Email confirmation date |
| card_saved_dt | Date | Card saved date |

**Person Fields:**

| Field Name | Type | Description |
|------------|------|-------------|
| hermes_id | Numerical | Internal Hermes ID |

**Deal Fields:**

| Field Name | Type | Description |
|------------|------|-------------|
| hermes_id | Numerical | Internal Hermes ID |
| All Company fields | Same as above | Deal inherits company fields |

After creating fields, run `make setup-fields` again to update your field mappings.

### 4. Create Admin Records

Use the automated setup command to create admin records from your Pipedrive users:

```bash
make setup-admins
```

This command will:
- Fetch all users from your Pipedrive account
- Show existing admin records
- Display available Pipedrive users to create admins for
- Let you select users (by index or "all")
- For each selected user, ask for their TC2 Admin ID
- Automatically configure them as:
  - Sales and support persons
  - Selling all plans (PAYG, Startup, Enterprise)
  - Selling to all regions (GB, US, AU, CA, EU, ROW)

**Example session:**
```
Existing Admins:
┌────┬────────────────┬──────────────────────┬────────┬──────────┐
│ ID │ Name           │ Email                │ TC2 ID │ PD ID    │
└────┴────────────────┴──────────────────────┴────────┴──────────┘

Fetching users from Pipedrive...

Pipedrive Users:
┌───────┬──────────────┬───────────────────┬──────────┬────────┐
│ Index │ Name         │ Email             │ PD ID    │ Active │
├───────┼──────────────┼───────────────────┼──────────┼────────┤
│ 1     │ John Smith   │ john@company.com  │ 12345678 │ ✓      │
│ 2     │ Jane Doe     │ jane@company.com  │ 87654321 │ ✓      │
└───────┴──────────────┴───────────────────┴──────────┴────────┘

Select users to create admin records for:
Enter indices separated by commas (e.g., 1,3,5) or "all" for all users
Selection: 1,2

Creating admin for: John Smith
TC2 Admin ID (leave empty to skip): 1
✓ Created admin: John Smith (ID: 1)

Creating admin for: Jane Doe
TC2 Admin ID (leave empty to skip): 2
✓ Created admin: Jane Doe (ID: 2)

✓ Admin setup complete!
```

### 5. Run Hermes

Start the development server:
```bash
make run
```

The server will start on `http://localhost:8000` with auto-reload enabled.

For production, use:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 6. Local Development with Webhooks

Since TC2 and Pipedrive need to send webhooks to Hermes, expose your local server:

```bash
ngrok http 8000
```

Then update your webhook URLs in TC2 and Pipedrive to use the ngrok URL.

## Adding Custom Fields

When you need to add a new custom field:

1. **Create in Pipedrive:**
   - Navigate to Settings > Data Fields
   - Create field with snake_case name (e.g., `new_field`)
   - Copy the field ID (API key)

2. **Add to Hermes models:**
   - Add to `app/main_app/models.py` in relevant model (Company, Contact, Deal):
     ```python
     new_field: Optional[str] = Field(default=None)
     ```

3. **Update field mappings:**
   - Edit `field_mappings_override.py`:
     ```python
     COMPANY_PD_FIELD_MAP = {
         # ... existing fields ...
         'new_field': 'your-field-id-from-pipedrive',
     }
     ```

4. **Update Pydantic models:**
   - Add to `app/pipedrive/models.py`:
     ```python
     new_field: Optional[str] = Field(
         default=None,
         validation_alias=COMPANY_PD_FIELD_MAP['new_field']
     )
     ```

5. **Create migration:**
   ```bash
   make migrate-create msg="Add new_field"
   make migrate
   ```

6. **Restart** the application

## Testing

Run the test suite:
```bash
make test
```

Run with coverage:
```bash
make test-cov
```

Tests are organized by module:
- `tests/main_app/` - Core functionality tests
- `tests/pipedrive/` - Pipedrive integration tests
- `tests/tc2/` - TC2 integration tests  
- `tests/callbooker/` - Callbooker tests

**Coverage Target:** 95%+

## Troubleshooting

### Field mapping errors on startup

Run `make setup-fields` to check which fields are missing in Pipedrive. Create any missing fields and update `field_mappings_override.py`.

### Webhooks not being received

1. Check ngrok is running and URL is correct
2. Verify webhook configuration in Pipedrive/TC2
3. Check Hermes logs for errors
4. Test webhook with curl:
   ```bash
   curl -X POST http://localhost:8000/pipedrive/callback/ \
     -H "Content-Type: application/json" \
     -d '{"event":"added","current":{}}'
   ```

### Admin not found errors

Ensure Admin records exist with correct TC2/Pipedrive IDs. Check `pd_owner_id` matches actual Pipedrive user IDs.

### Pipeline/Stage errors

1. Run `make setup` to sync pipelines from Pipedrive
2. Ensure at least one pipeline exists in Pipedrive
3. Check Config record has valid pipeline assignments

### Database migration issues

If migrations fail:
```bash
make reset-db  # Drops and recreates database
make setup     # Reconfigure pipelines
```

## Architecture

### Data Models

**Core Models:**
- `Admin` - Sales/support personnel linked to TC2 and Pipedrive
- `Company` - Organizations (customers/prospects)
- `Contact` - Individual contacts within companies
- `Deal` - Sales opportunities
- `Meeting` - Scheduled calls/meetings
- `Pipeline` - Sales pipelines from Pipedrive
- `Stage` - Pipeline stages
- `Config` - Application configuration

**Key Features:**
- All dates are timezone-aware (UTC)
- Foreign key relationships between models
- Unique constraints on external IDs
- Field mappings for Pipedrive custom fields

### Field Mapping System

Hermes uses a centralized field mapping system instead of database tables for custom fields:

1. **Default mappings** are defined in `app/pipedrive/field_mappings.py`
2. **Local overrides** can be added in `field_mappings_override.py` (gitignored)
3. **Pydantic models** use `validation_alias` to map incoming webhook data
4. **Sync tasks** use the mappings to send data to Pipedrive

This approach:
- Single source of truth for field IDs
- Type-safe at compile time
- Easy to update for new Pipedrive accounts
- No database queries for field lookups

### Sync Flow

**TC2 → Hermes → Pipedrive:**
1. TC2 sends webhook when client/SR changes
2. Hermes processes webhook and updates database
3. Background task syncs changes to Pipedrive

**Callbooker → Hermes → Pipedrive:**
1. Website sends booking request
2. Hermes creates/updates Company, Contact, Deal
3. Meeting is created in Google Calendar
4. Changes sync to Pipedrive

**Pipedrive → Hermes:**
1. Pipedrive sends webhook on changes
2. Hermes updates local database
3. Does NOT sync back to TC2 (one-way)

## Contributing

### Code Style

- Use single quotes for strings
- Modern type hints: `str | None` instead of `Optional[str]`
- Line length: 120 characters
- Format with ruff: `make format`
- Lint with ruff: `make lint`

### Testing

- Write tests for all new features
- Maintain 95%+ code coverage
- Use test fixtures from `tests/conftest.py`
- Follow existing test patterns (see `AGENTS.md`)

### Commits

- Use clear, descriptive commit messages
- Reference issue numbers where applicable
- Keep commits focused and atomic

## License

Proprietary - TutorCruncher Ltd
