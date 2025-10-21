# Hermes

Sales integration system connecting TutorCruncher (TC2), Pipedrive CRM, and Website Callbooker.

## Current Status

**Production Version**: v3 (Tortoise ORM)  
**In Development**: v4 (SQLModel)

## Project Structure

```
hermes/
├── app/                    # v3 Production code (Tortoise ORM)
├── tests/                  # v3 Tests
├── migrations/             # v3 Database migrations
├── v2_migration/          # Historical: v2 → v3 migration scripts
├── v3/                    # Archive: Old v3 code (kept for reference)
└── v4/                    # In Development: New v4 code (SQLModel)
    ├── app/
    ├── tests/
    └── migrations/
```

## Version History

### v3 (Current Production)
- **Framework**: FastAPI + Tortoise ORM
- **Database**: PostgreSQL
- **Key Features**:
  - TC2 webhook integration
  - Pipedrive CRM sync
  - Callbooker system
  - CustomField/CustomFieldValue architecture

### v4 (In Development)
- **Framework**: FastAPI + SQLModel
- **Database**: PostgreSQL  
- **Key Improvements**:
  - SQLModel ORM (async SQLAlchemy)
  - Pydantic v2
  - Field mapping system (replaces CustomField tables)
  - Single source of truth for Pipedrive field IDs
  - Better type safety and performance

## Quick Start

### v3 (Production)
```bash
# Install dependencies
make install-dev

# Run migrations
aerich upgrade

# Run tests
make test

# Run application
make run
```

### v4 (Development)
```bash
cd v4

# Install dependencies
uv sync --all-groups

# Run migrations
make migrate

# Run tests
make test

# Run application
make run
```

## Migration History

### v2 → v3
Completed October 2025. See `v2_migration/README.md` for details.

### v3 → v4
Planned. Migration scripts and documentation in `v4/` directory.

## Documentation

- **v3 Documentation**: See `app/` directory and code comments
- **v4 Documentation**: See `v4/AGENTS.md` for comprehensive development guide
- **Migration Docs**: See `v2_migration/README.md`

## Database

### v3 Schema
- Uses CustomField + CustomFieldValue for flexible field management
- Tortoise ORM migrations in `migrations/`

### v4 Schema  
- Direct field mapping (no CustomField tables)
- Alembic migrations in `v4/migrations/`
- Field IDs centralized in `v4/app/pipedrive/field_mappings.py`

## Tech Stack

### Both Versions
- **Language**: Python 3.10+
- **Framework**: FastAPI
- **Database**: PostgreSQL
- **External APIs**: TC2, Pipedrive v2, Google Calendar

### v3 Specific
- Tortoise ORM
- Pydantic v1
- Aerich (migrations)

### v4 Specific
- SQLModel (SQLAlchemy + Pydantic)
- Pydantic v2
- Alembic (migrations)
- Logfire (observability)

## Contributing

When working on v3 (production):
- Follow existing Tortoise ORM patterns
- Use Aerich for migrations
- Test thoroughly before deploying

When working on v4 (development):
- Follow `v4/AGENTS.md` guidelines
- Use single quotes for strings
- Modern type hints (`str | None` not `Optional[str]`)
- Test with `make test-cov` (maintain 95%+ coverage)

## License

Proprietary - TutorCruncher Ltd

