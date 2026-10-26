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
| Evaluation on a real document (NIST AI RMF 1.0) with local embeddings and a Groq LLM | Run locally; results saved in `eval/results_*.json` |
| Azure Document Intelligence, Azure AI Search, Azure OpenAI, Key Vault, Functions, App Insights, Ollama | Code written; not yet run against live services |
| GitHub Actions workflow | Lint, tests, evaluation gate and Docker build pass in CI; the deploy job is skipped until an Azure Function App is configured |

The default configuration runs fully offline: a local hybrid index (BM25 + hashed vectors), an extractive
answerer instead of an LLM, and pypdf for PDFs (with words split across line breaks rejoined). Azure services,
local embeddings and LLM providers are switched on with environment variables (see `.env.example`).

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

### Optional: local embeddings and a real LLM

```powershell
python -m pip install -r requirements-embeddings.txt
$env:EMBEDDINGS="fastembed"
$env:LLM_PROVIDER="groq"
$env:GROQ_API_KEY="..."            # set in your shell only; never commit it
$env:GROQ_MODEL="openai/gpt-oss-20b"
```

Groq's model list changes often; check which chat models your key can use at
`https://api.groq.com/openai/v1/models`. Re-ingest after changing the embedding setting so the index and queries
use the same vectors.

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
- **Embeddings** (`app/embeddings.py`): Azure OpenAI if configured, local `fastembed` (bge-small-en-v1.5) if
  `EMBEDDINGS=fastembed`, otherwise a deterministic hashing embedder that needs no downloads.
- **Refusal**: the answer is refused when fewer than `MIN_CONFIDENCE` (default 0.5) of the question's content
  words appear in any retrieved chunk. It is a cheap lexical gate and can wrongly refuse paraphrased questions.
- **Governance**: every answer, approval request, approval decision and executed action is written to the audit log
  (JSONL, also emitted to logging so Application Insights can pick it up).
- **Secrets**: env vars first, then Key Vault (`KEY_VAULT_URL`, managed identity). `ENV=prod` refuses the default JWT secret.

## Evaluation

There are three question sets.

**Regression set (runs in CI).** `eval/golden.jsonl`: 32 questions (24 answerable, 8 out-of-scope or
prompt-injection) over three small synthetic documents in `data/docs`, using the offline defaults. It keeps the
pipeline from breaking and says little about quality. All thresholds pass. One question fails ("What encryption is
used for backups?") because "encryption" and "encrypted" don't match without a proper stemmer.

**Development set.** `eval/golden_real.jsonl`: 38 questions (30 answerable, 8 out-of-scope or prompt-injection)
over NIST AI 100-1 (AI Risk Management Framework 1.0), indexed as 174 chunks.

**Held-out set.** `eval/golden_heldout.jsonl`: 13 questions (10 answerable, 3 out-of-scope) on passages not used
for the development set, written after the pipeline was settled and run once.

Metrics: recall@5, citation accuracy, faithfulness, refusal accuracy, p50/p95 latency. CI fails if recall@5 < 0.85,
faithfulness < 0.85, citation accuracy < 0.90 or refusal accuracy < 0.90.

### Results on the development set

Each row changes one thing from the row above it:

| Step | recall@5 | citation accuracy | refusal accuracy |
|---|---|---|---|
| Baseline: pypdf, hashed-vector retrieval, extractive answerer | 0.633 | 0.552 | 0.875 |
| Rejoin words hyphenated across line breaks | 0.833 | 0.759 | 0.875 |
| Swap pypdf for PyMuPDF | 0.833 | 0.759 | 0.875 |
| Add local embeddings (fastembed) | 0.900 | 0.724 | 0.875 |
| Add an LLM (Groq, `openai/gpt-oss-20b`) | 0.900 | 0.963 | 1.000 |

Faithfulness on the final configuration is 0.926 (a lexical proxy, see caveats).

What each step showed:

- **Extraction was the first bottleneck.** pypdf left fragments like "Manage- ment" and "abil- ity", which broke
  keyword matching. Rejoining hyphenated words fixed most of it. Part of that first jump also came from correcting a
  typo in one golden-set phrase.
- **PyMuPDF changed nothing**, so it was not kept.
- **Embeddings improved retrieval but not the answers.** Recall rose, but the extractive answerer often quoted a
  sentence from a neighbouring chunk.
- **The LLM fixed citation accuracy** and refused the one out-of-scope question the keyword gate let through.

### Held-out result

Same final configuration, 13 questions: recall@5 1.00, citation accuracy 1.00, refusal accuracy 1.00,
faithfulness 0.85. No failures.

### Known failures

Three questions are wrongly refused: *"How does the AI RMF define risk?"*, *"What do the letters in TEVV stand
for?"* and *"How does the framework define an AI system?"*. They are paraphrased "define X" questions whose words
don't appear in the retrieved passages, so the confidence gate blocks them before the LLM can answer. A fourth
(*"Why can lab measurements of AI risk be misleading?"*) retrieved the right passage but cited a different one.
Gating on embedding similarity instead of keyword coverage is the obvious next fix.

### Caveats

- The sets are small. On 30 answerable questions, one question moves a score by about 3 points.
- I looked at the development-set failures while making changes, so those figures are not clean held-out numbers.
- The held-out questions reuse the document's own wording, so they are easier than the paraphrased questions that
  failed on the development set. Treat the held-out result as a sanity check, not proof of generalisation.
- Faithfulness is a word-overlap proxy, not an LLM-judged score.
- Latency in the LLM runs includes Groq free-tier retries and is not representative of production.

To reproduce the real-document runs:

```powershell
$env:EMBEDDINGS="fastembed"; $env:LLM_PROVIDER="groq"; $env:GROQ_API_KEY="..."; $env:GROQ_MODEL="openai/gpt-oss-20b"
$env:EVAL_DOCS="data/real_docs"; $env:EVAL_GOLDEN="eval/golden_real.jsonl"; $env:EVAL_DELAY="3"
python eval/run_eval.py
```

Saved results for each step are in `eval/results_*.json`. `python -m scripts.check_golden` verifies that every
expected phrase exists in the extracted text, and `python -m scripts.diagnose` shows where the expected chunk ranks.

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
- The confidence gate and the faithfulness score are lexical heuristics, not semantic.
- The Azure integrations have not been run against live services.
- The local index is for development and is not meant for large corpora.