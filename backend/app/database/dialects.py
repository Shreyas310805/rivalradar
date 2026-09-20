"""Dialect-portable SQL constructs.

The application targets SQLite locally and PostgreSQL in production. Almost
everything SQLAlchemy emits is identical on both, but a few expressions are
not, and those live here rather than being written inline with a driver check
at each call site.
"""

from __future__ import annotations

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import ColumnElement, FunctionElement
from sqlalchemy.types import Date


class day_bucket(FunctionElement):  # noqa: N801  (SQL constructs are lowercase by convention)
    """Truncate a timestamp to its calendar day.

    There is no portable spelling for this:

      * SQLite has ``date(x)``, but ``CAST(x AS DATE)`` is wrong there — SQLite
        has no DATE type, so the cast applies NUMERIC affinity and
        ``'2026-09-19 22:38:00'`` comes back as the integer ``2026``.
      * PostgreSQL has no single-argument ``date()`` function at all; calling
        it raises ``function date(timestamp without time zone) does not
        exist``. The ANSI cast is the correct form there.

    So each dialect gets the spelling it actually supports. Both return
    something that renders as ``YYYY-MM-DD``: a string on SQLite, a
    ``datetime.date`` on PostgreSQL, which ``str()`` formats identically.
    """

    type = Date()
    name = "day_bucket"
    inherit_cache = True

    def __init__(self, column: ColumnElement) -> None:
        super().__init__(column)


@compiles(day_bucket)
def _day_bucket_default(element: day_bucket, compiler, **kw: object) -> str:  # noqa: ANN001
    """ANSI SQL, which is what PostgreSQL wants."""
    return f"CAST({compiler.process(element.clauses.clauses[0], **kw)} AS DATE)"


@compiles(day_bucket, "sqlite")
def _day_bucket_sqlite(element: day_bucket, compiler, **kw: object) -> str:  # noqa: ANN001
    return f"date({compiler.process(element.clauses.clauses[0], **kw)})"
