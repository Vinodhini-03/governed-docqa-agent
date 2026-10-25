"""Settings. Secrets resolve from env first, then Azure Key Vault (if KEY_VAULT_URL is set)."""
import os
from dataclasses import dataclass
from functools import lru_cache

DEFAULT_SECRET = "dev-secret-change-me"


def secret(name: str, default: str = "") -> str:
    val = os.getenv(name)
    if val:
        return val
    vault = os.getenv("KEY_VAULT_URL")
    if vault:
        try:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient

            client = SecretClient(vault_url=vault, credential=DefaultAzureCredential())
            return client.get_secret(name.replace("_", "-")).value or default
        except Exception:  # noqa: BLE001 - fall back rather than crash on cold start
            return default
    return default


@dataclass(frozen=True)
class Settings:
    env: str
    jwt_secret: str
    store: str
    llm_provider: str
    min_confidence: float
    top_k: int
    index_path: str
    audit_path: str
    outputs_dir: str
    docintel_endpoint: str
    docintel_key: str
    search_endpoint: str
    search_key: str
    search_index: str


@lru_cache
def get_settings() -> Settings:
    s = Settings(
        env=os.getenv("ENV", "dev"),
        jwt_secret=secret("JWT_SECRET", DEFAULT_SECRET),
        store=os.getenv("STORE", "local"),
        llm_provider=os.getenv("LLM_PROVIDER", "extractive"),
        min_confidence=float(os.getenv("MIN_CONFIDENCE", "0.5")),
        top_k=int(os.getenv("TOP_K", "5")),
        index_path=os.getenv("INDEX_PATH", "data/index.json"),
        audit_path=os.getenv("AUDIT_PATH", "data/audit.jsonl"),
        outputs_dir=os.getenv("OUTPUTS_DIR", "data/outputs"),
        docintel_endpoint=os.getenv("DOCINTEL_ENDPOINT", ""),
        docintel_key=secret("DOCINTEL_KEY"),
        search_endpoint=os.getenv("SEARCH_ENDPOINT", ""),
        search_key=secret("SEARCH_KEY"),
        search_index=os.getenv("SEARCH_INDEX", "docqa-chunks"),
    )
    if s.env == "prod" and s.jwt_secret == DEFAULT_SECRET:
        raise RuntimeError("JWT_SECRET must be set when ENV=prod")
    return s
