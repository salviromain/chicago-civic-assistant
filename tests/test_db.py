import datetime as dt
from decimal import Decimal

from app.db import _plain


def test_database_values_become_json_friendly():
    assert _plain(Decimal("721")) == 721 and isinstance(_plain(Decimal("721")), int)
    assert _plain(Decimal("0.5")) == 0.5
    assert _plain(dt.date(2026, 1, 1)) == "2026-01-01"
    assert _plain(dt.datetime(2026, 1, 1, 8, 30)) == "2026-01-01T08:30:00"
    assert _plain(dt.timedelta(days=1, hours=12)) == 1.5
    assert _plain(42.0) == 42 and isinstance(_plain(42.0), int) and _plain(0.49) == 0.49
    assert _plain("PHF") == "PHF" and _plain(None) is None
