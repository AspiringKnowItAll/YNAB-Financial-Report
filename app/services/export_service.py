"""
HTML and PDF export service.

Renders a ReportSnapshot to HTML via Jinja2, then optionally converts
to PDF via WeasyPrint.

- HTML export: standalone, self-contained file with embedded CSS and
  interactive Plotly charts (Plotly.js CDN).
- PDF export: print-optimised layout with data tables instead of charts
  (WeasyPrint does not execute JavaScript).

AI-generated markdown commentary is rendered to sanitised HTML via
bleach before insertion into either template.
"""

import asyncio
import json

import bleach
import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.models.report import ReportSnapshot

# ---------------------------------------------------------------------------
# Jinja2 environment (separate from the request-bound app instance)
# ---------------------------------------------------------------------------

_jinja_env = Environment(
    loader=FileSystemLoader("app/templates"),
    autoescape=select_autoescape(["html"]),
)


def _milliunit_to_dollars(value: int) -> str:
    dollars = abs(value) / 1000
    formatted = f"${dollars:,.2f}"
    return f"-{formatted}" if value < 0 else formatted


def _format_dollars(value: float) -> str:
    """Format a plain float (already in dollars) as a currency string."""
    return f"${value:,.2f}"


_jinja_env.filters["milliunit_to_dollars"] = _milliunit_to_dollars
_jinja_env.filters["format_dollars"] = _format_dollars

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALLOWED_TAGS = [
    "p", "br", "strong", "em", "b", "i", "ul", "ol", "li",
    "blockquote", "code", "pre", "h1", "h2", "h3", "h4",
]
_ALLOWED_ATTRS: dict = {}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _render_commentary(raw_markdown: str) -> str:
    """Convert AI markdown to sanitised HTML (matches reports router)."""
    html = markdown.markdown(raw_markdown, extensions=["nl2br"])
    return bleach.clean(html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS, strip=True)


def _parse_chart_data(snapshot: ReportSnapshot) -> tuple[str | None, str | None]:
    """Return (trend_json_string, category_json_string) from a snapshot."""
    trend: str | None = None
    category: str | None = None
    if snapshot.chart_data:
        try:
            data = json.loads(snapshot.chart_data)
            trend = data.get("trend")
            category = data.get("category")
        except (json.JSONDecodeError, AttributeError):
            pass
    return trend, category


def _parse_outliers(snapshot: ReportSnapshot) -> list:
    if snapshot.outliers_excluded:
        try:
            return json.loads(snapshot.outliers_excluded)
        except json.JSONDecodeError:
            pass
    return []


def _extract_trend_table(trend_json: str) -> list[dict]:
    """
    Parse Plotly trend chart JSON and return a list of monthly rows:
        [{month: str, income: float, spending: float, net: float}]
    Values are plain dollars (floats).
    """
    try:
        spec = json.loads(trend_json)
        months: list = spec["data"][0]["x"]
        income: list = spec["data"][0]["y"]
        spending: list = spec["data"][1]["y"]
        return [
            {
                "month": m,
                "income": float(i),
                "spending": float(s),
                "net": float(i) - float(s),
            }
            for m, i, s in zip(months, income, spending)
        ]
    except (KeyError, IndexError, json.JSONDecodeError, TypeError):
        return []


def _extract_category_table(category_json: str) -> list[dict]:
    """
    Parse Plotly category chart JSON and return a list of category rows:
        [{name: str, amount: float, average: float}]
    The spec stores bars bottom-to-top for the horizontal layout; we
    reverse for top-to-bottom display in a table.
    Values are plain dollars (floats).
    """
    try:
        spec = json.loads(category_json)
        names: list = spec["data"][0]["y"]
        amounts: list = spec["data"][0]["x"]
        averages: list = spec["data"][1]["x"]
        rows = [
            {"name": n, "amount": float(a), "average": float(avg)}
            for n, a, avg in zip(names, amounts, averages)
        ]
        return list(reversed(rows))
    except (KeyError, IndexError, json.JSONDecodeError, TypeError):
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def render_html(snapshot: ReportSnapshot, budget_name: str) -> str:
    """
    Render a report snapshot to a standalone HTML string for download.

    The output is self-contained: CSS is inlined, Plotly.js is loaded
    from CDN, and charts are interactive. No server-side resources are
    required after the file is saved.

    Returns:
        UTF-8 HTML string ready to serve as a file download.
    """
    trend_json, category_json = _parse_chart_data(snapshot)
    outliers = _parse_outliers(snapshot)
    commentary_html = _render_commentary(snapshot.ai_commentary) if snapshot.ai_commentary else None

    template = _jinja_env.get_template("reports/report_export.html")
    return template.render(
        snapshot=snapshot,
        budget_name=budget_name,
        trend_chart_json=trend_json,
        category_chart_json=category_json,
        outliers=outliers,
        commentary_html=commentary_html,
    )


async def render_pdf(snapshot: ReportSnapshot, budget_name: str) -> bytes:
    """
    Render a report snapshot to PDF bytes via WeasyPrint.

    Charts are replaced by data tables (WeasyPrint does not run JS).
    WeasyPrint is called in a thread executor to avoid blocking the
    async event loop.

    Returns:
        Raw PDF bytes suitable for streaming as a download response.
    """
    trend_json, category_json = _parse_chart_data(snapshot)
    outliers = _parse_outliers(snapshot)
    commentary_html = _render_commentary(snapshot.ai_commentary) if snapshot.ai_commentary else None

    trend_table = _extract_trend_table(trend_json) if trend_json else []
    category_table = _extract_category_table(category_json) if category_json else []

    template = _jinja_env.get_template("reports/report_pdf.html")
    html_string = template.render(
        snapshot=snapshot,
        budget_name=budget_name,
        trend_table=trend_table,
        category_table=category_table,
        outliers=outliers,
        commentary_html=commentary_html,
    )

    from weasyprint import HTML  # noqa: PLC0415 — deferred to avoid import cost at startup

    loop = asyncio.get_running_loop()
    pdf_bytes: bytes = await loop.run_in_executor(
        None, lambda: HTML(string=html_string).write_pdf()
    )
    return pdf_bytes
