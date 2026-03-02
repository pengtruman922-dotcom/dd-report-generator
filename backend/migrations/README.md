# Report Metadata Migration

This directory contains scripts for migrating report metadata from JSON files to SQLite database.

## Overview

The DD Report Generator originally stored report metadata in individual JSON files (`outputs/*.json`). To improve querying, filtering, and management capabilities, we've migrated to a SQLite database while maintaining backward compatibility with JSON files.

## Migration Strategy

**Dual-Write Pattern**: The system now writes to both database and JSON files:
- **Database**: Primary storage for queries and filtering
- **JSON files**: Backup and backward compatibility

## Files

### `migrate_reports_to_db.py`
Migrates all existing report JSON files to the database.

**Usage:**
```bash
cd backend
python migrations/migrate_reports_to_db.py
```

**Features:**
- Reads all `outputs/*.json` files (excluding `*_chunks.json`)
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

This ensures:
- No data loss if database fails
- Easy rollback if needed
- Gradual migration path
- Existing tools continue to work

## Rollback Plan

If issues occur, you can rollback by:

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
