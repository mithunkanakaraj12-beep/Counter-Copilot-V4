# Tests

Use synthetic yard data until customer data processing is explicitly authorized.

- fixtures/: synthetic yard, contacts, SKU catalog, inventory, prices, and messages.
- unit/: schema validation, lumber attributes, unit conversions, SKU matching, ATP, pricing, quote states, permissions, idempotency.
- integration/: API/database/storage/jobs/provider adapter contract tests.
- security/: tenant isolation, role checks, webhook verification, approval replay protection, STOP suppression, private files, and secret handling.
- hard_cases/: shorthand, missing fields, conflicting units, messy attachments, noisy audio, duplicates, and stale reports.

Write expected outputs for critical cases. Do not mark generated tests as passing until executed.
