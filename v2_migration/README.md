# Hermes v2 to v3 Migration

This directory contains the migration scripts and documentation for migrating from Hermes v2 to v3.

## Migration Date
October 2025

## What Changed
- **v2**: Older architecture
- **v3**: Current production system (Tortoise ORM)

## Migration Scripts

### `scripts/migrate_v2_to_v3.py`
Main migration script that migrates all data from v2 database to v3 database.

**Usage:**
```bash
cd v2_migration
pip install -r scripts/requirements.txt

# Run migration
V2_DATABASE_URL=postgresql://... V3_DATABASE_URL=postgresql://... python scripts/migrate_v2_to_v3.py
```

### `scripts/test_migration.py`
Test script to validate the migration.

## Migration Process

1. **Backup v2 database**
   ```bash
   pg_dump hermes > hermes_v2_backup.sql
   ```

2. **Create v3 database**
   ```bash
   createdb hermes_v3
   # Run v3 migrations
   ```

3. **Run migration**
   ```bash
   python scripts/migrate_v2_to_v3.py
   ```

4. **Verify migration**
   - Check record counts
   - Verify foreign key relationships
   - Test sample data

## Status
✅ Migration completed successfully

## Notes
- v2 database is archived
- v3 is now the production system
- This folder is kept for historical reference only

