# Report Metadata Migration

This directory contains historical scripts for migrating report metadata from JSON sidecars to SQLite.

## Overview

The DD Report Generator originally stored report metadata in individual JSON files (`outputs/*.json`). The current v3 runtime uses SQLite as the primary source of truth, while some JSON sidecars may still exist for historical reports and operational fallback.

## Migration Strategy

**Current runtime reality**:
- **Database**: primary source for reports, chunks, tasks, attachments, intake logs
- **JSON/Markdown sidecars**: historical compatibility artifacts that may still be read or synced for some report operations
- `*_chunks.json` is no longer part of the v3 runtime path

## Files

### `migrate_reports_to_db.py`
Migrates all existing report JSON files to the database.

**Usage:**
```bash
cd backend
python migrations/migrate_reports_to_db.py
```

**Features:**
- Reads all `outputs/*.json` metadata sidecars (excluding historical `*_chunks.json`)
- Inserts metadata into the `reports` table
- Skips reports that already exist in database
- Provides detailed progress and error reporting
- Preserves all fields including complex JSON structures

### `verify_migration.py`
Verifies that the migration was successful by comparing database records with JSON files.

**Usage:**
```bash
cd backend
python migrations/verify_migration.py
```

**Checks:**
- All JSON files have corresponding database records
- Key fields match between JSON and database
- No extra or missing records
- Data integrity verification

### `remove_report_versions_table.py`
Removes the deprecated `report_versions` table after the version-history feature was retired.

**Usage:**
```bash
cd backend
python migrations/remove_report_versions_table.py
```

**Features:**
- Checks whether `report_versions` still exists
- Prints the row count before cleanup
- Creates a full SQLite backup before dropping the table
- Skips safely when the table is already gone

## Database Schema

The `reports` table includes:

**Core Fields:**
- `report_id` (PRIMARY KEY)
- `bd_code`, `company_name`, `project_name`
- `industry`, `province`, `city`, `district`
- `is_listed`, `stock_code`, `website`

**Financial Fields:**
- `revenue`, `net_profit`
- `revenue_yuan`, `net_profit_yuan`, `valuation_yuan`

**Scoring Fields:**
- `score` (REAL)
- `rating`, `manual_rating`

**System Fields:**
- `status`, `owner`
- `created_at`, `updated_at`
- `file_size`

**Complex Fields (JSON):**
- `metadata_json` - Full metadata backup
- `locked_fields` - User-edited fields
- `push_records` - FastGPT push history
- `attachments` - Attachment metadata

**Indexes:**
- `bd_code`, `company_name`, `owner`, `status`
- `created_at DESC`, `rating`

## Migration Process

1. **Initialize Database**
   ```bash
   # Database is auto-initialized on first run
   python main.py
   ```

2. **Run Migration**
   ```bash
   cd backend
   python migrations/migrate_reports_to_db.py
   ```

3. **Verify Migration**
   ```bash
   python migrations/verify_migration.py
   ```

4. **Test Application**
   - Start the backend server
   - Verify report list loads correctly
   - Test filtering and search
   - Create a new report to test dual-write

## Backward Compatibility

The system maintains full backward compatibility:

1. **Reading**: Tries database first, falls back to JSON
2. **Writing**: Writes to both database and JSON
3. **Deletion**: Deletes from both database and JSON
4. **Updates**: Updates both database and JSON

This ensured:
- no data loss during migration
- gradual cutover from JSON metadata to database storage
- historical reports remained readable during the transition

## Rollback Plan

If you are operating on a historical branch and issues occur, you can rollback by:

1. Stop the backend server
2. The JSON files remain intact as backup
3. Remove database changes (optional)
4. Restart with JSON-only mode (modify code to skip database)

## Performance Benefits

Database storage provides:
- **Fast queries**: Indexed searches on company name, bd_code, rating
- **Efficient filtering**: SQL WHERE clauses vs. file scanning
- **Pagination**: Server-side pagination for large datasets
- **Aggregations**: Count, sum, group by operations
- **Concurrent access**: Better handling of simultaneous requests

## Future Enhancements

With database in place, we can now implement:
- Advanced search and filtering
- Server-side pagination
- Report statistics and analytics
- Batch operations
- Version history tracking
- Audit logs
