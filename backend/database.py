import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# ---------------------------------------------------------------------------
# 连接串优先级：
#   1) DATABASE_URL（生产 Postgres 或任意 SQLAlchemy URL）
#   2) EMS_DB（SQLite 文件名/路径，开发默认 ems.dev.db / 生产回滚用 ems.db）
# ---------------------------------------------------------------------------
_EXPLICIT_URL = (os.environ.get("DATABASE_URL") or "").strip()
_DB_PATH = Path(os.environ.get("EMS_DB", "ems.db")).expanduser()
if not _DB_PATH.is_absolute():
    _DB_PATH = Path(__file__).resolve().parent / _DB_PATH

if _EXPLICIT_URL:
    DATABASE_URL = _EXPLICIT_URL
else:
    DATABASE_URL = f"sqlite:///{_DB_PATH}"

_IS_SQLITE = DATABASE_URL.startswith("sqlite")

_engine_kwargs: dict = {"pool_pre_ping": True}
if _IS_SQLITE:
    _engine_kwargs["connect_args"] = {"check_same_thread": False, "timeout": 60}
else:
    # Postgres：常驻服务，适度连接池
    _engine_kwargs["pool_size"] = int(os.environ.get("EMS_DB_POOL_SIZE", "10"))
    _engine_kwargs["max_overflow"] = int(os.environ.get("EMS_DB_MAX_OVERFLOW", "20"))

engine = create_engine(DATABASE_URL, **_engine_kwargs)


if _IS_SQLITE:

    @event.listens_for(engine, "connect")
    def _sqlite_on_connect(dbapi_conn, _connection_record):
        """WAL + busy_timeout，降低 ICT/AOI 与仓库导入互锁（仅 SQLite）。"""
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=60000")
            cur.execute("PRAGMA temp_store=MEMORY")
        finally:
            cur.close()

    with engine.connect() as _conn:
        _conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        _conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
        _conn.exec_driver_sql("PRAGMA busy_timeout=60000")
        _conn.commit()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def db_engine_label() -> str:
    """日志/启动脚本用：一眼看出当前连的是哪类库。"""
    if _IS_SQLITE:
        return f"sqlite:{_DB_PATH.name}"
    # 脱敏：不打印密码
    try:
        from sqlalchemy.engine import make_url

        u = make_url(DATABASE_URL)
        return f"{u.drivername}://{u.host}:{u.port}/{u.database}"
    except Exception:
        return "postgresql"
