"""FastAPI app package for the student frontend."""

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.config import _load_config
from core.database import init_database
from core.logging import configure_logging_from_dict, log
from core.service import ServiceLocator, set_global_services
from core.translate import LanguageService
from shared.conversation import get_conversation_manager as _get_conversation_manager
from shared.driver import get_driver as _get_driver
from shared.llm import LLMManager
from shared.module_handler import module_handler
from shared.prompt_manager import get_prompt_manager, load_all_prompts
from shared.semantic_eval import SemanticEvaluator
from shared.settings import UserSettingsManager
from shared.users import get_user_manager as _get_user_manager

load_dotenv()


def bootstrap_services() -> ServiceLocator:
    config = _load_config()
    configure_logging_from_dict(config.get("logging", {}))

    db_path = config.get("database.path", "sqlite:///data/app.db")
    init_database(use_memory=False, db_path=db_path)

    user_manager = _get_user_manager()
    user_manager.init_default_users(config)

    conversation_manager = _get_conversation_manager()
    llm_manager = LLMManager(config)
    user_settings_manager = UserSettingsManager()
    driver = _get_driver()
    language_service = LanguageService()

    # Get default language from config, fallback to "en"
    default_language = config.get("app.default_language", "en")
    language_service.set_default_language(default_language)

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pm = get_prompt_manager()
    load_all_prompts(root_dir)

    semantic_eval = SemanticEvaluator(llm_manager)

    def no_cache(fn):
        return fn

    services = ServiceLocator()
    services.register("cache", no_cache)
    services.register("config", config)
    services.register("user_manager", user_manager)
    services.register("db_manager", __import__("core.database", fromlist=["get_db_manager"]).get_db_manager())
    services.register("conversation_manager", conversation_manager)
    services.register("prompt_manager", pm)
    services.register("llm_manager", llm_manager)
    services.register("user_settings_manager", user_settings_manager)
    services.register("driver", driver)
    services.register("language_service", language_service)
    services.register("semantic_eval", semantic_eval)

    set_global_services(services)

    module_handler.initialize()
    module_handler.activate_all()

    return services


_SERVICES = bootstrap_services()

jwt_secret = os.getenv("JWT_SECRET")
if not jwt_secret:
    jwt_secret = secrets.token_urlsafe(48)
    os.environ["JWT_SECRET"] = jwt_secret
    log("warning", "JWT_SECRET is not set. Generated ephemeral secret for current process.")

app = FastAPI(title="Coach Student Frontend API")

if os.getenv("ENV", "dev").lower() != "prod":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

from api.auth import router as auth_router
from api.chat import router as chat_router
from api.conversations import router as conversations_router

app.include_router(auth_router)
app.include_router(conversations_router)
app.include_router(chat_router)

frontend_dist = Path(__file__).parent.parent / "frontend_dist"
assets_dir = frontend_dist / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")


@app.get("/", include_in_schema=False)
async def serve_index():
    index_file = frontend_dist / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Frontend not built yet. Run frontend build first."}


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")

    file_path = frontend_dist / full_path
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path)

    index_file = frontend_dist / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Frontend not built yet. Run frontend build first.", "path": full_path}
