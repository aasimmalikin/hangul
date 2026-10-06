"""db/base.py's connect hook: a pinned database address that goes bad is dropped and
the connection retried on another one, instead of failing every new connection until
the pin expires (seen as 500s on any route that needed a fresh connection)."""
import socket
import time

import pytest

from harness.db import base


class OperationalError(Exception):
    pass


class FakeDialect:
    loaded_dbapi = type("DBAPI", (), {"OperationalError": OperationalError})

    def __init__(self, dead):
        self.dead, self.tried = set(dead), []

    def connect(self, *cargs, **cparams):
        self.tried.append(cparams.get("hostaddr"))
        if cparams.get("hostaddr") in self.dead:
            raise OperationalError("connection timeout expired")
        return "conn"


@pytest.fixture
def addresses(monkeypatch):
    monkeypatch.setattr(base, "_pinned", {})
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", (ip, 5432)) for ip in ("1.1.1.1", "2.2.2.2")])
    monkeypatch.setattr(base, "_probe", lambda ip, port, timeout: ip)   # both answer a TCP probe


def test_a_bad_pinned_address_is_dropped_and_another_tried(addresses):
    base._pinned["db.example"] = ("1.1.1.1", time.monotonic())
    d = FakeDialect(dead={"1.1.1.1"})
    assert base._pin_reachable_address(d, None, (), {"host": "db.example"}) == "conn"
    assert d.tried == ["1.1.1.1", "2.2.2.2"]
    assert base._pinned["db.example"][0] == "2.2.2.2"        # the next connection goes straight there


def test_a_healthy_pin_connects_once(addresses):
    base._pinned["db.example"] = ("2.2.2.2", time.monotonic())
    d = FakeDialect(dead=set())
    base._pin_reachable_address(d, None, (), {"host": "db.example"})
    assert d.tried == ["2.2.2.2"]


def test_when_every_address_fails_the_error_still_surfaces(addresses):
    d = FakeDialect(dead={"1.1.1.1", "2.2.2.2"})
    with pytest.raises(OperationalError):
        base._pin_reachable_address(d, None, (), {"host": "db.example"})
    assert len(d.tried) == 2                                  # one retry, not a loop
