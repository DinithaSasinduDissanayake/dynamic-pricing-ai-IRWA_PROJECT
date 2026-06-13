import os
# Trigger reload for env vars
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from contextlib import asynccontextmanager
from starlette.middleware.base import BaseHTTPMiddleware
import structlog

from core.chat_db import init_chat_db, cleanup_empty_threads
from core.auth_db import init_db_async
from backend.routers import auth, settings, threads, messages, streaming, prices, catalog, alerts, debug, collector

from core.agents.alert_service import api as alert_api
from core.agents.price_optimizer.agent import PricingOptimizerAgent
from core.agents.data_collector.agent import DataCollectorAgent
from core.agents.data_collector.repo import DataRepo
from core.agents.data_collector.collector import DataCollector
from core.agents.proposal_logger import ProposalLogger

logger = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Database initialization
    await init_db_async()
    init_chat_db()
    cleanup_empty_threads()
    
    if os.environ.get("EXPORT_OPENAPI_ONLY", "0") in {"1", "true", "yes", "on"}:
        yield
        return
    
    # Initialize agents
    pricing_optimizer = None
    data_collector = None
    proposal_logger = None

    # try:
    #     logger.info("agent_init_start", agent="PricingOptimizerAgent")
    #     pricing_optimizer = PricingOptimizerAgent()
    #     logger.info("agent_init_success", agent="PricingOptimizerAgent")
    # except Exception as e:
    #     logger.error("agent_init_failed", agent="PricingOptimizerAgent", error=str(e))
    
    # try:
    #     logger.info("agent_init_start", agent="DataCollectorAgent")
    #     from core.settings import get_settings
    #     db_path = get_settings().resolve_app_db()
    #     data_collector_repo = DataRepo(db_path)
    #     await data_collector_repo.init()
    #     reactive_collector = DataCollector(data_collector_repo)
    #     app.state.reactive_collector = reactive_collector
    #     data_collector = DataCollectorAgent(
    #         repo=data_collector_repo,
    #         check_interval_seconds=180
    #     )
    #     logger.info("agent_init_success", agent="DataCollectorAgent")
    # except Exception as e:
    #     logger.warning("agent_init_failed", agent="DataCollectorAgent", error=str(e))
    
    # try:
    #     logger.info("agent_init_start", agent="ProposalLogger")
    #     proposal_logger = ProposalLogger()
    #     logger.info("agent_init_success", agent="ProposalLogger")
    # except Exception as e:
    #     logger.error("agent_init_failed", agent="ProposalLogger", error=str(e))
    
    # Start agents
    logger.info("agents_starting")
    await alert_api.start()

    # Start consolidated PricingService for modular monolith setup
    try:
        from core.agents.pricing_service import PricingService
        ps = PricingService()
        await ps.start()
        app.state.pricing_service = ps
    except Exception:
        logger.warning("pricing_service_failed_to_start")

    # Start outbox flusher for reliable event delivery
    try:
        from core.agents.agent_sdk.event_bus import get_bus
        from core.agents.agent_sdk.outbox import start_outbox_flusher
        bus = get_bus()
        await start_outbox_flusher(bus)
        logger.info("outbox_flusher_started")
    except Exception:
        logger.warning("outbox_flusher_failed_to_start")

    
    # if pricing_optimizer:
    #     try:
    #         await pricing_optimizer.start()
    #         logger.info("agent_started", agent="PricingOptimizerAgent")
    #     except Exception as e:
    #         logger.error("agent_start_failed", agent="PricingOptimizerAgent", error=str(e))
    
    # if data_collector:
    #     try:
    #         await data_collector.start()
    #         logger.info("agent_started", agent="DataCollectorAgent")
    #     except Exception as e:
    #         logger.error("agent_start_failed", agent="DataCollectorAgent", error=str(e))
    
    # if proposal_logger:
    #     try:
    #         await proposal_logger.start()
    #         logger.info("agent_started", agent="ProposalLogger")
    #     except Exception as e:
    #         logger.error("agent_start_failed", agent="ProposalLogger", error=str(e))
    
    yield
    
    # Cleanup on shutdown
    if data_collector:
        await data_collector.stop()
    if proposal_logger:
        await proposal_logger.stop()


app = FastAPI(title="FluxPricer Auth + Chat API", lifespan=lifespan, debug=True)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"message": str(exc), "traceback": traceback.format_exc()},
    )
 
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")


@app.get("/", response_class=HTMLResponse)
def root_index():
    try:
        return HTMLResponse((FRONTEND_DIST / "index.html").read_text(encoding="utf-8"))
    except Exception:
        return HTMLResponse("<h1>FluxPricer API</h1><p>Frontend not built. Run: cd frontend && npm run build</p>")


# Capture the original host environment value for UI_REQUIRE_LOGIN so pytest can override it
_ORIG_UI_REQUIRE_LOGIN = os.environ.get("UI_REQUIRE_LOGIN")


def _require_login_enabled() -> bool:
    try:
        if os.getenv("PYTEST_CURRENT_TEST") is not None:
            return os.environ.get("UI_REQUIRE_LOGIN", "").lower() in {"1", "true", "yes", "on"}
        try:
            from core.settings import get_settings
            flag = getattr(get_settings(), "ui_require_login", False)
            if flag:
                return True
        except Exception:
            pass
        if _ORIG_UI_REQUIRE_LOGIN is not None:
            try:
                return _ORIG_UI_REQUIRE_LOGIN.lower() in {"1", "true", "yes", "on"}
            except Exception:
                return False
        return False
    except Exception:
        return False


class ChatAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Note: Auth middleware temporarily simplified during migration to fastapi-users
        if not _require_login_enabled():
            return await call_next(request)
        path = request.url.path or ""
        if path.startswith("/api/login") or path.startswith("/api/register") or path.startswith("/api/me") or path.startswith("/api/settings"):
            return await call_next(request)
        return await call_next(request)


app.add_middleware(ChatAuthMiddleware)

app.include_router(auth.router)
app.include_router(settings.router)
app.include_router(threads.router)
app.include_router(messages.router)
app.include_router(messages.router_global)
app.include_router(streaming.router)
app.include_router(prices.router)
app.include_router(catalog.router)
app.include_router(alerts.router)
app.include_router(debug.router)
app.include_router(collector.router)
