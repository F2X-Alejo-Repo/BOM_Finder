# 17 - Data Migration and Upgrade

## Purpose

Define schema evolution, desktop upgrade behavior, and recovery controls for SQLite data.
This gate is mandatory before closing persistence-dependent phases.

## Schema Versioning Policy

- All schema changes must be Alembic migrations.
- No destructive migration without explicit rollback or repair path.
- Every migration includes idempotency and downgrade notes.

## Compatibility Targets

- Forward migration supported for all released app versions in support window.
- Opening a newer DB with an older app is unsupported and must show clear error.

## Startup Upgrade Flow

1. Detect current DB schema version.
2. Create timestamped backup before migration.
3. Run pending migrations inside transaction boundaries.
4. Validate post-migration integrity checks.
5. On failure, restore backup and mark app in degraded mode with guidance.

## Backup and Restore Contract

- Backups stored in user data directory with retention policy.
- Restore tool must support latest backup and user-selected backup.
- Restore operation logs outcome with correlation ID.

## Migration Testing Requirements

- Upgrade tests across at least two previous schema snapshots.
- Corrupt DB scenario tests.
- Interrupted migration simulation tests.
- Downgrade or repair path tests where applicable.

## Repair Playbook (Minimum)

- Identify broken migration revision
- Restore last good backup
- Re-run patched migration
- Validate row counts and checksum metrics

## Gate Criteria

- Migration suite passes in CI
- Backup/restore verified
- Upgrade notes included in release artifacts
