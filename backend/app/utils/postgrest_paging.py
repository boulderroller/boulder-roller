"""Paging helpers for the pinned postgrest-py client (0.13.x).

Two facts about that client's wire format break naive offset pagination:

* ``range(start, end)`` sends the header ``Range: start-(end - 1)``. Its end is
  exclusive, unlike PostgREST's inclusive header and supabase-js, so
  ``range(offset, offset + n - 1)`` returns n - 1 rows. A loop that stops on
  ``len(page) < n`` therefore stops after its first page.
* Every ``order()`` call becomes its own ``order`` query parameter, and
  PostgREST applies only the first one. Chained tie-breakers are dropped, and
  rows that tie on the first column can repeat or go missing between pages.

Paging loops keep a :class:`PageCursor`: it advances by ``len(page)``, ends the
read on a page too short to be full under either client convention, and raises
rather than read forever when a server or a fake ignores the window. Sort keys
go through :func:`order_by`. A read that must return exactly ``n`` rows, such as
an API page or a bounded scan, uses :func:`window`, whose ``limit``/``offset``
parameters mean the same thing in every client version.
"""

from __future__ import annotations

from typing import Any, Sized, TypeVar

_QueryT = TypeVar("_QueryT")

# A paged read longer than this many pages is not reading new rows.
MAX_PAGES = 1000


class PagingRunaway(RuntimeError):
    """A paged read did not end: the server is not honouring the window."""


class PageCursor:
    """Offset and termination for one paged read of ``size``-row windows.

    ``advance(page)`` ends the read on an empty page or on one shorter than
    ``size - 1`` rows: the pinned client's ``range()`` returns ``size - 1``
    rows for a full page, newer clients and :func:`window` return ``size``. A
    full page moves the offset past the rows that arrived. A read still going
    after ``max_pages`` pages raises :class:`PagingRunaway`, so every loop
    driven by a cursor terminates whatever the server returns.
    """

    def __init__(self, size: int, *, max_pages: int = MAX_PAGES) -> None:
        if size < 1 or max_pages < 1:
            raise ValueError("PageCursor needs size >= 1 and max_pages >= 1")
        self.size = size
        self.max_pages = max_pages
        self.offset = 0
        self.pages = 0

    def advance(self, page: Sized) -> bool:
        """Record one page; True while the read continues."""
        self.pages += 1
        if not page or len(page) < self.size - 1:
            return False
        if self.pages >= self.max_pages:
            raise PagingRunaway(
                f"paged read still returning full pages after {self.pages} "
                f"pages of {self.size} rows"
            )
        self.offset += len(page)
        return True


def order_by(query: _QueryT, *columns: str, desc: bool = False) -> _QueryT:
    """Sort by every column in one ``order`` parameter.

    Columns before the last may carry a direction (``"visit_count.desc"``).
    The last column's direction is ``desc``, as for ``order()``, because newer
    clients append it to the parameter themselves.
    """
    if not columns:
        raise ValueError("order_by needs at least one column")
    if "." in columns[-1]:
        raise ValueError("give the last column's direction with desc=")
    query_any: Any = query
    joined = ",".join(columns)
    return query_any.order(joined, desc=True) if desc else query_any.order(joined)


def window(query: _QueryT, offset: int, size: int) -> _QueryT:
    """Request exactly rows ``[offset, offset + size)``.

    The server's row cap can still return fewer rows than asked for.
    """
    if offset < 0 or size < 1:
        raise ValueError("window needs offset >= 0 and size >= 1")
    query_any: Any = query
    return query_any.offset(offset).limit(size)
