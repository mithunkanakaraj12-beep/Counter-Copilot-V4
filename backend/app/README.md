# Backend application package

Suggested modules:
- api/ — versioned HTTP routes and request/response validation.
- core/ — configuration, security, shared errors, utilities.
- db/ — models, sessions, repositories, migrations.
- schemas/ — typed contracts aligned with docs/DATA_CONTRACT.md.
- services/ — contacts, extraction, SKU matching, inventory, pricing, approvals.
- workers/ — durable jobs, retries, and event processing.

Keep core business rules independent from provider SDKs and web framework details where practical.
