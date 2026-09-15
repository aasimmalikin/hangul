from sqlalchemy import create_engine
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
    future = True,
    # The dev database is remote (Neon, ap-southeast-1) reached over a flaky
    # WSL2 NAT path. A hung SYN was observed to stall a request for minutes,
    # so bound the connect; and keepalives stop the NAT from silently dropping
    # idle pooled connections, which is what forced those reconnects.
    connect_args = {
        "connect_timeout": 10,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 3,
    },
)

SessionLocal = sessionmaker(bind = engine, expire_on_commit = False, future = True)