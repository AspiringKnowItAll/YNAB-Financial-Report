"""
Profile setup wizard routes.

Multi-step wizard that collects personal context used by the AI report generator:
  - Household size
  - Income type (salary / variable / mixed)
  - Financial goals (free text)
  - Housing type (rent / own / other)
  - Additional notes (free text)

GET  /setup   → Render wizard form (pre-populated if profile already exists)
POST /setup   → Validate, save profile, set setup_complete=True, redirect to dashboard
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user_profile import UserProfile
from app.schemas.setup import UserProfileUpdate

router = APIRouter(tags=["setup"])
templates = Jinja2Templates(directory="app/templates")


async def _get_or_create_profile(db: AsyncSession) -> UserProfile:
    """Return the singleton UserProfile row (id=1), creating it if absent."""
    result = await db.execute(select(UserProfile).where(UserProfile.id == 1))
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = UserProfile(id=1)
        db.add(profile)
        await db.flush()
    return profile


@router.get("/setup", response_class=HTMLResponse)
async def get_setup(request: Request, db: AsyncSession = Depends(get_db)):
    profile = await _get_or_create_profile(db)
    return templates.TemplateResponse("setup/setup.html", {
        "request": request,
        "profile": profile,
        "errors": [],
    })


@router.post("/setup", response_class=HTMLResponse)
async def post_setup(
    request: Request,
    db: AsyncSession = Depends(get_db),
    household_size: str = Form(default=""),
    income_type: str = Form(default=""),
    financial_goals: str = Form(default=""),
    housing_type: str = Form(default=""),
    notes: str = Form(default=""),
):
    profile = await _get_or_create_profile(db)
    errors: list[str] = []

    try:
        data = UserProfileUpdate(
            household_size=int(household_size) if household_size.strip() else 0,
            income_type=income_type,  # type: ignore[arg-type]
            financial_goals=financial_goals,
            housing_type=housing_type,  # type: ignore[arg-type]
            notes=notes or None,
        )
    except (ValidationError, ValueError) as exc:
        if hasattr(exc, "errors"):
            for e in exc.errors():
                field = e["loc"][0] if e.get("loc") else "form"
                errors.append(f"{field}: {e['msg']}")
        else:
            errors.append(str(exc))

    if errors:
        # Re-bind submitted values so the form retains user input
        profile.household_size = int(household_size) if household_size.strip().isdigit() else None
        profile.income_type = income_type or None
        profile.financial_goals = financial_goals or None
        profile.housing_type = housing_type or None
        profile.notes = notes or None
        await db.rollback()
        return templates.TemplateResponse("setup/setup.html", {
            "request": request,
            "profile": profile,
            "errors": errors,
        }, status_code=422)

    profile.household_size = data.household_size
    profile.income_type = data.income_type
    profile.financial_goals = data.financial_goals
    profile.housing_type = data.housing_type
    profile.notes = data.notes
    profile.setup_complete = True

    await db.commit()
    return RedirectResponse("/", status_code=302)
