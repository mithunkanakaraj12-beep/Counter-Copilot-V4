# Counter Copilot V4 — Handoff

## Current status
Repository organization and specification branch only. No application code has been implemented or tested. External integrations are not connected.

## Repository
- Repository: mithunkanakaraj12-beep/Counter-Copilot-V4
- Default branch: main
- Working branch: setup/v4-repository-foundation

## Workstream ownership proposal
- Claude 1: backend, data contract implementation, extraction, catalog/inventory/pricing rules, approval state machine, backend tests.
- Claude 2: frontend, email/SMS/voice adapters, infrastructure/deployment configuration, integration tests.
- ChatGPT: independent review and test design.
- Gemini: transcription/extraction benchmarking using synthetic data.
- Project owner: scope/contract approvals, repository governance, account setup, customer discovery, merges, and coordination of a competent technical operator for live deployment.

Do not assume chat assistants share memory, files, credentials, or execution environments. Confirm each one's actual ability to run code and integration tests.

## Immediate next actions
1. Review V4_SCOPE.md, ARCHITECTURE.md, DATA_CONTRACT.md, and DECISIONS.md.
2. Confirm exact framework versions and typed API schemas.
3. Verify target yard phone, email, messaging, inventory, and pricing systems before promising connectors.
4. Claude 1 creates backend skeleton, canonical schemas, synthetic fixtures, and tests.
5. Claude 2 creates minimal frontend shell and mocked adapters against the approved contract.
6. Identify the real technical operator for environment setup, live connections, deployment, monitoring, and incident response.
7. Plan first pilot as the smallest complete, customer-authorized workflow.

## Tests and integrations
- Repository structure: scaffolded on this setup branch; review before merging.
- Application tests: none; no application code exists.
- Provider integrations: not connected.
- Customer data: none authorized/configured.

## Contract proposal v0.1 (awaiting review)
- Branch: work/backend-foundation
- Files changed: docs/DATA_CONTRACT.md, docs/DECISIONS.md, docs/HANDOFF.md, contracts/v0_1/
- Decisions: D-013 proposed, not approved.
- Tests run: `python -m pytest contracts/v0_1` on Python 3.13, 134 passed. These check the contract files only.
- Tests not run: official OpenAPI 3.1 meta-schema validation; application tests (no application code).
- Open issues/blockers: U-01 to U-20 in DATA_CONTRACT.md section 16.
- Next action and owner: project owner reviews and decides; no dependent implementation before approval.

## Session close-out template
- Branch/commit:
- Files changed:
- Decisions:
- Tests run and exact result:
- Tests not run:
- Open issues/blockers:
- Next action and owner:
