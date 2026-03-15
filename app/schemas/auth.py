from pydantic import BaseModel, Field, field_validator


class MasterPasswordCreate(BaseModel):
    """Input schema for the first-run master password creation form."""

    password: str = Field(min_length=12, max_length=1024)
    password_confirm: str = Field(min_length=12, max_length=1024)

    @field_validator("password_confirm")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("Passwords do not match.")
        return v


class MasterPasswordUnlock(BaseModel):
    """Input schema for the unlock form (entered after container restart)."""

    password: str = Field(min_length=1, max_length=1024)


class RecoveryCodeSubmit(BaseModel):
    """Input schema for the recovery code form."""

    code: str = Field(
        min_length=23,
        max_length=23,
        description="Format: XXXXX-XXXXX-XXXXX-XXXXX (23 chars including dashes)",
    )

    @field_validator("code")
    @classmethod
    def normalize_code(cls, v: str) -> str:
        return v.strip().upper()
