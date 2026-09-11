import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from database import Base, SessionLocal, engine
import models  # noqa: F401 — 注册 ORM 元数据
from migrate import migrate
from routers import (
    auth,
    dashboard,
    engineering,
    hr,
    ict_gate,
    laser,
    master,
    material_control,
    orders,
    packing,
    planning,
    presales,
    process_scan,
    purchase,
    production,
    outsource,
    quotation,
    sales,
    scheduling,
    shipping,
    sync,
    warehouse,
    aftersales,
    warehouse_aux,
    finance,
    gl,
)
from security_hardening import (
    check_api_auth,
    check_rate_limit,
    is_probe_path,
    security_cfg,
    security_headers,
)
from sync_scheduler import reload_scheduler, shutdown_scheduler
from system_auth import parse_token, user_must_change_password
from user_service import ensure_default_users

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    migrate()
    db = SessionLocal()
    try:
        ensure_default_users(db)
        from master_data_service import ensure_master_defaults

        ensure_master_defaults(db)
        from gerber_sync import reaudit_all_gerber_packages
        from placement_sync import reaudit_all_placement_files
        from refmap_sync import reaudit_all_refmap_files

        import os
        if os.environ.get("EMS_SKIP_STARTUP_AUDIT") != "1":
            reaudit_all_gerber_packages(db)
            reaudit_all_placement_files(db)
            reaudit_all_refmap_files(db)
        else:
            logging.getLogger(__name__).warning("已跳过启动期 Gerber/坐标/位号图重审计")
        from substitution_service import reload_substitution_cache_from_db

        n = reload_substitution_cache_from_db(db)
        if n:
            logging.getLogger(__name__).info("替代料缓存已预热：%s 条规则", n)
        db.commit()
    finally:
        db.close()
    reload_scheduler()
    yield
    shutdown_scheduler()


# 关闭公开 API 文档，降低被探测面
app = FastAPI(
    title="EMS",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(GZipMiddleware, minimum_size=500)
_sec = security_cfg()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_sec["cors_origins"],
    allow_origin_regex=_sec.get("cors_origin_regex"),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Auth-Token", "X-Api-Key", "Accept"],
)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    path = request.url.path

    if is_probe_path(path):
        resp = JSONResponse(status_code=404, content={"detail": "Not Found"})
        security_headers(resp)
        return resp

    # 文档入口一律 404（即使误开也挡）
    if path in ("/docs", "/redoc", "/openapi.json", "/docs/", "/redoc/"):
        resp = JSONResponse(status_code=404, content={"detail": "Not Found"})
        security_headers(resp)
        return resp

    limited = check_rate_limit(request)
    if limited is not None:
        security_headers(limited)
        return limited

    denied = check_api_auth(request)
    if denied is not None:
        security_headers(denied)
        return denied

    response = await call_next(request)
    security_headers(response)
    return response


@app.middleware("http")
async def no_cache_html_and_classic(request: Request, call_next):
    """局域网浏览器易缓存旧壳页/classic 脚本，导致看起来像「没同步」。"""
    response = await call_next(request)
    path = request.url.path
    if (
        path in ("/", "/classic", "/classic/")
        or path.endswith(".html")
        or path.startswith("/classic/")
        or (path.startswith("/static/classic/") and path.endswith((".js", ".css", ".html")))
        or (
            not path.startswith(("/api/", "/assets/", "/static/", "/docs", "/redoc", "/openapi"))
            and "." not in path.rsplit("/", 1)[-1]
        )
    ):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


PASSWORD_CHANGE_SKIP = {
    "/api/auth/login",
    "/api/auth/status",
    "/api/auth/change-password",
    "/api/health",
}


@app.middleware("http")
async def enforce_password_change(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in PASSWORD_CHANGE_SKIP:
        token = request.headers.get("X-Auth-Token") or request.query_params.get("access_token")
        if token:
            principal = parse_token(token)
            if principal and user_must_change_password(principal.user_id):
                resp = JSONResponse(status_code=403, content={"detail": "请先修改初始密码"})
                security_headers(resp)
                return resp
    return await call_next(request)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail
    # 统一脱敏：5xx 不回内部信息
    if exc.status_code >= 500:
        detail = "服务暂时不可用"
    elif not isinstance(detail, (str, list, dict)):
        detail = "请求失败"
    resp = JSONResponse(status_code=exc.status_code, content={"detail": detail})
    security_headers(resp)
    return resp


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    resp = JSONResponse(status_code=422, content={"detail": "请求参数无效"})
    security_headers(resp)
    return resp


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("未处理异常 %s %s", request.method, request.url.path)
    resp = JSONResponse(status_code=500, content={"detail": "服务暂时不可用"})
    security_headers(resp)
    return resp


app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(orders.router)
app.include_router(packing.router)
app.include_router(sync.router)
app.include_router(warehouse.router)
app.include_router(engineering.router)
app.include_router(scheduling.router)
app.include_router(material_control.router)
app.include_router(quotation.router)
app.include_router(laser.router)
app.include_router(process_scan.router)
app.include_router(ict_gate.router)
app.include_router(hr.router)
app.include_router(master.router)
app.include_router(presales.router)
app.include_router(sales.router)
app.include_router(planning.router)
app.include_router(purchase.router)
app.include_router(production.router)
app.include_router(outsource.router)
app.include_router(shipping.router)
app.include_router(aftersales.router)
app.include_router(warehouse_aux.router)
app.include_router(finance.router)
app.include_router(gl.router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

VUE_DIR = STATIC_DIR / "vue"
VUE_ASSETS = VUE_DIR / "assets"
if VUE_ASSETS.exists():
    app.mount("/assets", StaticFiles(directory=VUE_ASSETS), name="vue_assets")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/classic")
@app.get("/classic/")
def classic_index():
    classic_file = STATIC_DIR / "classic" / "index.html"
    if classic_file.exists():
        return FileResponse(
            classic_file,
            headers={"Cache-Control": "no-cache"},
        )
    return RedirectResponse(url="/")


@app.get("/")
def index():
    vue_index = VUE_DIR / "index.html"
    if vue_index.exists():
        return FileResponse(vue_index, headers={"Cache-Control": "no-cache"})
    classic_file = STATIC_DIR / "classic" / "index.html"
    if classic_file.exists():
        return FileResponse(classic_file)
    return {"status": "ok"}


def _serve_vue_spa():
    vue_index = VUE_DIR / "index.html"
    if vue_index.exists():
        return FileResponse(vue_index, headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="Not Found")


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    """Vue history 模式：子路径刷新/直链需回退到 index.html。"""
    if full_path.startswith(("api/", "static/", "assets/", "classic/")):
        raise HTTPException(status_code=404, detail="Not Found")
    if full_path in ("docs", "redoc", "openapi.json"):
        raise HTTPException(status_code=404, detail="Not Found")
    return _serve_vue_spa()
