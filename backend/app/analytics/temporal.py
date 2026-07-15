from __future__ import annotations

import calendar
from datetime import date

from app.schemas.analytics import BurnedAreaTemporalQuery, ResolvedTemporalWindow

BA300_AVsoftwareLABLE_FROM = date(2018, 1, 1)
BA300_SOURCE_PRODUCT = "CLMS BA300 monthly v4"
DAY_DERIVATION = "Daily view derived retrospectively from monthly BA300 date-of-burn data"
MONTH_DERIVATION = "DOB-filtered monthly BA300"
YEAR_DERIVATION = "Monthly BA300 v4 annual combination"


class UnsupportedTemporalQuery(ValueError):
    pass


def month_bounds(value: date) -> tuple[date, date]:
    last_day = calendar.monthrange(value.year, value.month)[1]
    return date(value.year, value.month, 1), date(value.year, value.month, last_day)


def year_bounds(value: date) -> tuple[date, date]:
    return date(value.year, 1, 1), date(value.year, 12, 31)


def default_context_scope(query: BurnedAreaTemporalQuery) -> str:
    if query.context_scope:
        return query.context_scope
    if query.granularity == "day":
        return "selected-month"
    if query.granularity == "month":
        return "selected-year"
    return "loaded-range"


def resolve_temporal_window(query: BurnedAreaTemporalQuery) -> ResolvedTemporalWindow:
    if query.cursor < BA300_AVsoftwareLABLE_FROM:
        raise UnsupportedTemporalQuery(
            "CLMS BA300 monthly v4 is available from 2018 onward; earlier periods are unsupported."
        )
    if query.display_mode != "period":
        raise UnsupportedTemporalQuery(
            "Cumulative burned-area mode is not enabled yet; use display_mode='period'."
        )

    if query.granularity == "day":
        active_start = active_end = query.cursor
        derivation = DAY_DERIVATION
    elif query.granularity == "month":
        active_start, active_end = month_bounds(query.cursor)
        derivation = MONTH_DERIVATION
    else:
        active_start, active_end = year_bounds(query.cursor)
        derivation = YEAR_DERIVATION

    scope = default_context_scope(query)
    if scope == "selected-month":
        context_start, context_end = month_bounds(query.cursor)
    elif scope == "selected-year":
        context_start, context_end = year_bounds(query.cursor)
    elif scope == "loaded-range":
        context_start, context_end = BA300_AVsoftwareLABLE_FROM, year_bounds(query.cursor)[1]
    else:
        context_start, context_end = BA300_AVsoftwareLABLE_FROM, year_bounds(date.today())[1]

    return ResolvedTemporalWindow(
        active_start=active_start,
        active_end=active_end,
        context_start=context_start,
        context_end=context_end,
        granularity=query.granularity,
        display_mode=query.display_mode,
        source_product=BA300_SOURCE_PRODUCT,
        derivation_method=derivation,
    )
