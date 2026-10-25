# Architecture

```mermaid
flowchart LR
  PDF[Public PDFs] --> DI[Azure AI Document Intelligence<br/>prebuilt-layout]
  DI --> CH[Chunking + embeddings]
  CH --> AS[(Azure AI Search<br/>hybrid index)]
  U[Client] -->|JWT| API[FastAPI on Azure Functions]
  API --> G[Guardrails]
  G --> R[Retrieve + confidence check]
  R --> AS
  R --> LLM[Provider layer<br/>Groq / Ollama / Azure OpenAI / extractive]
  API --> AG[LangGraph agent]
  AG --> AP{Human approval<br/>approver role}
  AP -->|approved| T[Tools: save summary, escalate]
  API --> AUD[(Audit log + App Insights)]
  KV[Key Vault] -.secrets.-> API
```

Request path for `/agent/run`: guardrails -> retrieval -> confidence gate (refuse if low) -> answer with
citations -> plan action -> **interrupt for approval** -> execute only if approved. Every step is audit-logged.

Known limitation: the agent's pending-approval state lives in an in-process `MemorySaver`. With several
Function instances, or after a restart, pending approvals are lost. Swap in a persistent LangGraph
checkpointer (for example Postgres or Cosmos DB based) before real use.
