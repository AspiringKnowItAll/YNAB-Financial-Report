"""
HTML and PDF export service.

Renders a ReportSnapshot to HTML via Jinja2, then optionally converts
to PDF via WeasyPrint.

AI-generated markdown commentary is rendered to HTML with bleach sanitisation
before insertion into the template.

Implemented in Phase 7.
"""

from app.models.report import ReportSnapshot


async def render_html(snapshot: ReportSnapshot) -> str:
    """
    Render a report snapshot to a standalone HTML string.

    Returns:
        UTF-8 HTML string ready to serve or feed into WeasyPrint.
    """
    raise NotImplementedError


async def render_pdf(snapshot: ReportSnapshot) -> bytes:
    """
    Render a report snapshot to PDF bytes via WeasyPrint.

    Returns:
        Raw PDF bytes suitable for streaming as a download response.
    """
    raise NotImplementedError
