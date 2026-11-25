# Adapters

**Proposed owner:** Claude 2 for provider integrations; Claude 1 owns core schemas and orchestration.

Adapters isolate vendor-specific APIs/payloads from Counter Copilot's internal event model. Each must authenticate source events where supported, normalize according to docs/DATA_CONTRACT.md, preserve source IDs, implement idempotency/retry behavior, and include mocks/contract tests.

Planned: email, SMS/MMS, voice, transcription, and language-model adapters. Counter Copilot owns message normalization, storage, processing, and business logic. Adapters do not create public phone or mobile network access.
