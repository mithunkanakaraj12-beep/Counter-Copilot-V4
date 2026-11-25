# Backend

**Proposed owner:** Claude 1.

Responsibilities: FastAPI API, database models/migrations, canonical schemas, durable background jobs, extraction orchestration, SKU matching, inventory ATP/coverage, optional deterministic quote pricing, approval state machine, and backend tests.

Keep provider-specific parsing in adapters, not core business logic. Implement against docs/DATA_CONTRACT.md. No application code has been added yet.
