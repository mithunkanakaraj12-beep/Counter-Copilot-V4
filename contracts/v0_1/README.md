# Data contract v0.1 (proposal)

Interface definitions only. No server, database or worker is implemented here.
Rules are in [docs/DATA_CONTRACT.md](../../docs/DATA_CONTRACT.md).

| File | Contents |
|---|---|
| `models.py` | Pydantic models: API payloads and `ExtractionProposal` (model-adapter output) |
| `api.py` | Operation list used for generation |
| `generate_openapi.py` | Builds `openapi.yaml` |
| `openapi.yaml` | Generated OpenAPI 3.1 document. Do not edit by hand |
| `examples/` | Synthetic payloads, all fictional |
| `test_contract.py` | Consistency checks on these artifacts, not application tests |

## Run the checks

From the repository root:

```
python -m pip install -r contracts/v0_1/requirements.txt
python contracts/v0_1/generate_openapi.py
python -m pytest contracts/v0_1
```

The checks do not validate `openapi.yaml` against the official OpenAPI 3.1 meta-schema.
Run a dedicated OpenAPI validator before approval.
