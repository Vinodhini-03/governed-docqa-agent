# Governed Document Q&A Agent (Azure)

A question-answering agent over documents: Azure AI Document Intelligence for extraction, Azure AI Search for
hybrid retrieval, a FastAPI answer API with citations, a LangGraph agent with a **human approval gate**,
guardrails, JWT + RBAC, an audit log, a golden-set evaluation that gates CI, and a GitHub Actions pipeline.

See [docs/architecture.md](docs/architecture.md) for the diagram.

## Project status

| Area | Status |
|---|---|
| Chunking, retrieval, citations, guardrails, RBAC, approval flow, audit log | Built and tested locally (10 automated tests) |
| Golden-set evaluation + CI threshold gate | Built; runs locally and in CI |
| Azure Document Intelligence, Azure AI Search, Azure OpenAI, Key Vault, Functions, App Insights, Groq/Ollama | Code written; not yet run against live services |
| GitHub Actions workflow | Lint, tests, evaluation gate and Docker build pass in CI; the deploy job is skipped until an Azure Function App is configured |

The default configuration runs fully offline: a local hybrid index (BM25 + hashed vectors), an extractive
answerer instead of an LLM, and pypdf for PDFs. Azure services and LLM providers are switched on with
environment variables (see `.env.example`).

## Quick start (Windows PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m scripts.ingest data/docs
python -m uvicorn app.main:app --reload
```

Then open http://localhost:8000/docs, log in with `POST /token`, click **Authorize**, and try `/ask`.
Run the tests and evaluation with:

```powershell
python -m pytest -q
python eval/run_eval.py
```

Demo users (override with the `DEMO_USERS` JSON variable; replace with Entra ID for real use):
`alice/alice-pass` (reader), `bob/bob-pass` (reader + approver), `admin/admin-pass` (all roles, including `/audit`).

## Endpoints

| Route | Role | Purpose |
|---|---|---|
| `POST /token` | none | Get a JWT |
| `POST /ask` | reader | Answer with citations; refuses when confidence is low |
| `POST /agent/run` | reader | Agent run. If the question asks to *save/export* or *escalate/flag/notify/email*, it pauses with `pending_approval` |
| `POST /agent/approve/{thread_id}` | approver | `{"approved": true/false}`; the action runs only if approved |
| `GET /audit` | admin | Recent audit entries |

## Design choices

- **Provider layer** (`app/llm.py`): `LLM_PROVIDER=extractive|groq|ollama|azure_openai`. Azure OpenAI is optional.
- **Refusal**: the answer is refused when fewer than `MIN_CONFIDENCE` (default 0.5) of the question's content
  words appear in any retrieved chunk. It is a cheap lexical gate and can wrongly refuse paraphrased questions.
- **Governance**: every answer, approval request, approval decision and executed action is written to the audit log
  (JSONL, also emitted to logging so Application Insights can pick it up).
- **Secrets**: env vars first, then Key Vault (`KEY_VAULT_URL`, managed identity). `ENV=prod` refuses the default JWT secret.

## Evaluation

`eval/golden.jsonl` has 32 questions (24 answerable, 8 out-of-scope or prompt-injection) over three synthetic
sample documents in `data/docs`. Metrics: recall@5, citation accuracy, faithfulness, refusal accuracy, p50/p95 latency.
CI fails if recall@5 < 0.85, faithfulness < 0.85, citation accuracy < 0.90 or refusal accuracy < 0.90.

Latest local run (offline defaults, sample documents):

| Metric | Value |
|---|---|
| recall@5 | 1.00 |
| citation accuracy | 1.00 (on answered questions) |
| faithfulness | 1.00 (lexical proxy) |
| refusal accuracy | 1.00 |
| latency p50 / p95 | ~1 ms / ~2 ms (local index only, no network or LLM) |

These numbers are a smoke test, not a benchmark: the corpus is small and synthetic, the questions were written
alongside it, and the extractive answerer copies sentences, so faithfulness is close to trivial. One question
fails: *"What encryption is used for backups?"* is wrongly refused because "encryption" and "encrypted" do not
match without a proper stemmer. Next steps are evaluating on real public PDFs with a larger question set, running
against Azure AI Search and a real LLM, and adding an LLM-judged faithfulness metric.

## Deploy to Azure

1. Create a budget alert in the portal, then review and run `scripts/azure_setup.sh` (verify free-tier limits first).
2. Put `JWT_SECRET`, `DOCINTEL_KEY`, `SEARCH_KEY` in Key Vault; set app settings (`STORE=azure`, `ENV=prod`, endpoints, `KEY_VAULT_URL`).
3. Index: `STORE=azure DOCINTEL_ENDPOINT=... python -m scripts.ingest path/to/pdfs`.
4. GitHub: add secret `AZURE_FUNCTIONAPP_PUBLISH_PROFILE` and repo variable `AZURE_FUNCTIONAPP_NAME`; push to `main`.

Pipeline (`.github/workflows/ci.yml`): lint -> tests -> golden-set eval (gate) -> Docker build -> Functions deploy (main only).
The `Dockerfile` serves the same app with uvicorn for container hosting.

## Limitations

- Pending approvals are held in memory (`MemorySaver`); use a persistent checkpointer for multi-instance or restart safety.
- Demo auth and the user list are for demonstration only.
- Confidence gating and faithfulness scoring are lexical heuristics, not semantic.
- The local index is for development and is not meant for large corpora.