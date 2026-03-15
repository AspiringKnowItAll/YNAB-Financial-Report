"""
Shared Jinja2 templates instance with custom filters registered.

All routers must import `templates` from here — never create a new
Jinja2Templates instance in a router, as custom filters would not be
registered on it.
"""

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")
templates.env.autoescape = True  # XSS protection — auto-escape all template output


def milliunit_to_dollars(value: int) -> str:
    """Convert YNAB milliunits (int) to a formatted dollar string."""
    dollars = value / 1000
    return f"${dollars:,.2f}"


templates.env.filters["milliunit_to_dollars"] = milliunit_to_dollars
