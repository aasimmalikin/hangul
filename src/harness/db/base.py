import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from harness.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()

engine = create_engine(
    _settings.database_url,
    pool_pre_ping = True, 
    pool_size = 5,
    max_overflow = 10,
    # Neon's pooler drops idle connections; recycle ours first so a request
    # never inherits a dead one (pre_ping would catch it, but at reconnect cost).
    pool_recycle = 240,
    future = True,
    # The dev database is remote (Neon, ap-southeast-1) reached over a flaky
    # WSL2 NAT path. A hung SYN was observed to stall a request for minutes,
    # so bound the connect; and keepalives stop the NAT from silently dropping
    # idle pooled connections, which is what forced those reconnects.
    connect_args = {
        "connect_timeout": 4,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 3,
    },
)

SessionLocal = sessionmaker(bind = engine, expire_on_commit = False, future = True)


# A query that never answers must fail, not hang a request (or the startup
# lifespan, which would leave uvicorn accepting but never serving). Set per
# connection with SET rather than as a startup parameter: Neon's pooler
# (PgBouncer) rejects `options=-c statement_timeout=...` at connect time.
@event.listens_for(engine, "connect")
def _set_statement_timeout(dbapi_connection, _record) -> None:
    with dbapi_connection.cursor() as cur:
        cur.execute("SET statement_timeout = 20000")


# ---------------------------------------------------------------- fast connect
#
# The dev database is behind a hostname with several addresses; from WSL the
# IPv6 ones are unreachable and one IPv4 silently drops SYNs, so a connect
# that happens to try that one first burns the whole connect_timeout. Before
# each new connection, probe the IPv4 addresses in parallel (~100 ms when
# healthy) and pin the first that answers via `hostaddr` (the hostname stays
# for TLS/SNI). Cached for a few minutes; skipped for local hosts.

_PIN_TTL_S = 300
_pinned: dict[str, tuple[str, float]] = {}


def _probe(ip: str, port: int, timeout: float) -> str | None:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return ip
    except OSError:
        return None


def fastest_hostaddr(host: str, port: int = 5432, timeout: float = 1.5) -> str | None:
    now = time.monotonic()
    hit = _pinned.get(host)
    if hit and now - hit[1] < _PIN_TTL_S:
        return hit[0]
    try:
        ips = sorted({ai[4][0] for ai in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)})
    except socket.gaierror:
        return None
    if len(ips) <= 1:
        return ips[0] if ips else None
    with ThreadPoolExecutor(max_workers=len(ips)) as pool:
        futures = [pool.submit(_probe, ip, port, timeout) for ip in ips]
        for f in as_completed(futures):
            ip = f.result()
            if ip:
                _pinned[host] = (ip, now)
                return ip
    return None


@event.listens_for(engine, "do_connect")
def _pin_reachable_address(dialect, conn_rec, cargs, cparams):
    host = cparams.get("host") or engine.url.host
    if not host or host in ("localhost", "127.0.0.1") or host.endswith(".local"):
        return
    ip = fastest_hostaddr(host, int(cparams.get("port") or engine.url.port or 5432))
    if ip:
        cparams["hostaddr"] = ip
    # returning nothing lets the dialect connect with the adjusted params


def warm_pool(n: int | None = None) -> int:
    """Open (and return to the pool) n connections so the first requests after
    boot do not each pay the connect cost. Called from the API lifespan."""
    n = n or engine.pool.size()

    def one() -> bool:
        try:
            with engine.connect() as c:
                c.exec_driver_sql("select 1")
            return True
        except Exception:  # noqa: BLE001 - best effort, the request path retries anyway
            return False

    # opened concurrently and held until all are up, so the pool really ends
    # up with n distinct connections rather than one reused n times
    with ThreadPoolExecutor(max_workers=n) as pool:
        return sum(pool.map(lambda _: one(), range(n)))
