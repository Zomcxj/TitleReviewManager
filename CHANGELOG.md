# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased] - 2026-06-25

### Added
- **Alembic Database Migrations**: Introduced Alembic for professional database schema management.
  - Removed manual SQL migrations from `seed.py`.
  - Added `alembic/` directory and initial migration script.
- **Automated Testing**:
  - **Backend**: Configured `pytest` and added initial tests for `auth` and `customers` APIs.
  - **Frontend**: Configured `vitest` and added an initial unit test for the `auth` store.
- **Environment Management**:
  - Created `.env.example` to document required environment variables.
  - Created `backend/.env` for local development configuration.
  - `backend/auth.py` now requires `JWT_SECRET_KEY` to be set, improving security.
- **Documentation**: Updated `AGENTS.md` and `docs/deployment.md` to reflect the new development workflow.

### Changed
- `seed.py` is now only responsible for populating data, not schema creation.
- `main.py` no longer creates database tables on startup; this is now handled by Alembic.
