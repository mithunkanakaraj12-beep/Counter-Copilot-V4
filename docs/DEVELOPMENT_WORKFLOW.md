# Development Workflow

## Source of truth
GitHub stores code and versioned decisions. Chat history is not authoritative. Before each coding session, provide the current scope, architecture, data contract, and HANDOFF.md.

## Ownership
- Claude 1 (proposed): backend, canonical schemas, extraction, SKU/inventory/pricing rules, approval state machine, backend tests.
- Claude 2 (proposed): frontend, channel adapters, deployment configuration, integration tests.
- ChatGPT: independent architecture/code/security review and test design.
- Gemini: transcription and extraction benchmarking on synthetic labeled cases.
- Project owner: scope decisions, repository governance, approved secrets/account setup, customer discovery/authorization, merge decisions, and technical-operator coordination.

Confirm that each assistant's environment can access files, use a terminal, install dependencies, and execute tests. If it cannot, its code is unexecuted until run elsewhere.

## Branch and PR process
1. Work on a feature branch, not main.
2. Keep one coherent change per PR.
3. Run relevant tests in a real environment.
4. PR description states purpose, changed areas, tests run/not run, risks, and any contract changes.
5. Review contract compatibility, security, and tests before merging.
6. Update HANDOFF.md.

Suggested branch names: claude-1/backend-foundation, claude-2/frontend-adapters, feature/<name>, fix/<name>.

## Contract changes
Propose in DECISIONS.md; identify affected API consumers, schemas, fixtures, tests; obtain project-owner approval; update the contract and all dependent code together.

## Security
Never commit .env, API keys, access tokens, passwords, customer messages, call recordings, inventory exports, or customer price books. Use synthetic examples. Verify webhook signatures. Enforce yard isolation on every API and storage path. Keep files private and links short-lived. Audit employee and outbound actions.

## Testing
Unit-test schema validation, lumber attribute parsing, approved unit conversions, SKU matching, ATP, pricing, state transitions, permissions, and idempotency. Integration-test database/storage/jobs/adapters. Security-test tenant isolation, replayed approvals, STOP suppression, webhook authentication, private files, and secret handling.

## Production readiness
A local demo is not a production service. Live use needs a responsible operator, approved provider accounts, customer permissions, secure always-on hosting, monitoring, backups, fallback/rollback, incident response, and written pilot authorization.
