import os

from dotenv import load_dotenv

load_dotenv()


def parse_cors_origins(raw: str | None) -> list[str]:
    """Comma-separated browser origins allowed to call the API."""
    default = ["http://localhost:5173", "http://localhost:4173"]
    if not raw or not raw.strip():
        return default
    origins = [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]
    return origins or default


def env_bool(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).lower() == "true"


REQUIRED = [
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_JWT_SECRET",
    "SUPABASE_DB_URL",
    "GROQ_API_KEY",
    "YOUTUBE_API_KEY",
    "EMAIL_API_KEY",
    "SEARX_URL",
]

missing = [v for v in REQUIRED if not os.environ.get(v)]
if missing:
    raise RuntimeError(f"missing env: {', '.join(missing)}")


class Settings:
    SUPABASE_URL: str = os.environ["SUPABASE_URL"]
    SUPABASE_ANON_KEY: str = os.environ["SUPABASE_ANON_KEY"]
    SUPABASE_SERVICE_ROLE_KEY: str = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    SUPABASE_JWT_SECRET: str = os.environ["SUPABASE_JWT_SECRET"]
    SUPABASE_DB_URL: str = os.environ["SUPABASE_DB_URL"]
    GROQ_API_KEY: str = os.environ["GROQ_API_KEY"]
    YOUTUBE_API_KEY: str = os.environ["YOUTUBE_API_KEY"]
    EMAIL_API_KEY: str = os.environ["EMAIL_API_KEY"]
    EMAIL_FROM: str = os.environ.get("EMAIL_FROM", "Kite <onboarding@resend.dev>")
    SEARX_URL: str = os.environ["SEARX_URL"]
    CORS_ORIGINS: list[str] = parse_cors_origins(os.environ.get("CORS_ORIGINS"))
    ENABLE_SCHEDULER: bool = env_bool("ENABLE_SCHEDULER", "true")
    # Groq retired llama-3.3-70b-versatile on 2026-08-16; keep the model overridable.
    GROQ_MODEL: str = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
    DISCOVERY_V2: bool = env_bool("DISCOVERY_V2", "false")
    KB_FEED: bool = env_bool("KB_FEED", "false")
    KB_STACK_MIN_USERS: int = int(os.environ.get("KB_STACK_MIN_USERS", "3"))
    KB_RETENTION_DAYS: int = int(os.environ.get("KB_RETENTION_DAYS", "14"))

    # --- Phase 10: dynamic feed pipeline (all optional, never in REQUIRED) ---
    FEED_V3: bool = env_bool("FEED_V3", "false")

    # Additional LLM providers. Absent keys drop out of the cascade automatically.
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
    OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
    OPENROUTER_MODEL: str = os.environ.get(
        "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"
    )
    GROQ_SMALL_MODEL: str = os.environ.get("GROQ_SMALL_MODEL", "openai/gpt-oss-20b")

    INTERNAL_TRIGGER_SECRET: str = os.environ.get("INTERNAL_TRIGGER_SECRET", "")

    # Per-cycle LLM budget. The governor spends from the top of the ranked list down.
    LLM_MAX_REQUESTS_PER_CYCLE: int = int(os.environ.get("LLM_MAX_REQUESTS_PER_CYCLE", "60"))
    LLM_MAX_TOKENS_PER_CYCLE: int = int(os.environ.get("LLM_MAX_TOKENS_PER_CYCLE", "120000"))

    # Keep every category warm so picking one at onboarding is not a cold start.
    PREFILL_ON_STARTUP: bool = env_bool("PREFILL_ON_STARTUP", "true")
    PREFILL_TARGET_ARTICLES: int = int(os.environ.get("PREFILL_TARGET_ARTICLES", "8"))
    PREFILL_STALE_HOURS: float = float(os.environ.get("PREFILL_STALE_HOURS", "12"))

    COLLECT_MAX_CONCURRENCY: int = int(os.environ.get("COLLECT_MAX_CONCURRENCY", "8"))
    FEED_HALF_LIFE_HOURS: float = float(os.environ.get("FEED_HALF_LIFE_HOURS", "48"))
    FEED_STACK_HALF_LIFE_HOURS: float = float(
        os.environ.get("FEED_STACK_HALF_LIFE_HOURS", "336")
    )

    # Daily AI quiz (niche picker + LLM-generated questions). Off by default.
    QUIZ_ENABLED: bool = env_bool("QUIZ_ENABLED", "false")


settings = Settings()
