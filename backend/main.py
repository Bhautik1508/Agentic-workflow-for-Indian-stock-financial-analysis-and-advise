from dotenv import load_dotenv
load_dotenv()

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router as api_router

logger = logging.getLogger(__name__)


async def _probe_llm_health() -> None:
    """Log CRITICAL when the LLM tier is broken at boot.

    Groq retired both configured models and every analysis failed for days with
    nothing to indicate why. A dead LLM tier should be the loudest line in the
    log, not something you learn from a user report.
    """
    try:
        from llm import full_report

        report = await full_report(live=False)
        if report.get("healthy"):
            logger.info(
                f"[startup] LLM providers healthy (primary: {report.get('primary_provider')})"
            )
            return
        for provider in report.get("providers", []):
            if not provider.get("healthy"):
                logger.critical(
                    f"[startup] LLM provider '{provider.get('provider')}' is NOT healthy: "
                    f"{provider.get('error')}. Configured models: "
                    f"{provider.get('configured_models')}. "
                    f"Analyses will fail or silently degrade to the fallback tier."
                )
        if report.get("error"):
            logger.critical(f"[startup] {report['error']}")
    except Exception as exc:  # a health probe must never break boot
        logger.warning(f"[startup] LLM health probe could not run: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run as a background task, not inline: a slow or down vendor must not
    # delay startup or fail Render's health check. LLM_STARTUP_CHECK=0 skips it.
    task = None
    if (os.getenv("LLM_STARTUP_CHECK", "1") or "1").strip().lower() not in ("0", "false", "no"):
        task = asyncio.create_task(_probe_llm_health())

    yield

    if task and not task.done():
        task.cancel()


app = FastAPI(
    title="StockSage AI Backend",
    description="Multi-Agent Indian Stock Market Analyzer API",
    version="1.0.0",
    lifespan=lifespan,
)

# --- CORS ---
# `allow_origin_regex=r"https://.*\.vercel\.app"` with `allow_credentials=True`
# let ANY Vercel deployment — including one an attacker owns — make credentialed
# cross-origin calls to this API, and every /analyze call spends real tokens.
#
# Two changes:
#   1. Credentials are off. Nothing here uses cookies or an Authorization
#      header, so allowing them bought nothing and cost the wildcard's safety.
#   2. The preview-deploy regex is opt-in via ALLOWED_ORIGIN_REGEX rather than
#      hardcoded open. Scope it to your own project, e.g.
#      ALLOWED_ORIGIN_REGEX=^https://my-app-[a-z0-9]+-myteam\.vercel\.app$
_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

_origin_regex = (os.getenv("ALLOWED_ORIGIN_REGEX") or "").strip() or None
_allow_credentials = (os.getenv("CORS_ALLOW_CREDENTIALS", "0") or "0").strip().lower() in ("1", "true", "yes")

if _allow_credentials and _origin_regex:
    # Refusing to fail silently: this is the exact combination that made the
    # API reachable from anyone's deployment.
    logger.critical(
        "[cors] CORS_ALLOW_CREDENTIALS is on together with ALLOWED_ORIGIN_REGEX. "
        "Any origin matching that pattern can make credentialed requests. "
        "Disabling credentials — set explicit ALLOWED_ORIGINS instead."
    )
    _allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=_origin_regex,
    allow_credentials=_allow_credentials,
    allow_methods=["GET", "OPTIONS"],   # this API is read-only
    allow_headers=["*"],
)

# Include routers
app.include_router(api_router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
