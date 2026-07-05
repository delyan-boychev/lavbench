from pydantic import BaseModel, Field


class RegisterCompetitorSchema(BaseModel):
    name: str = Field(..., min_length=1)
    surname: str = Field(..., min_length=1)
    middle_name: str = Field(..., min_length=1)
    birth_date: str = Field(..., min_length=1)
    grade: str = Field(..., min_length=1)
    school: str = Field(..., min_length=1)
    city: str = Field(..., min_length=1)
    challenge_id: str = Field(..., min_length=1)
    email: str | None = Field(default=None)


class CreateUserSchema(BaseModel):
    username: str | None = Field(default=None)
    email: str | None = Field(default=None)
    password: str | None = Field(default=None)
    name: str = Field(..., min_length=1)
    surname: str = Field(..., min_length=1)
    middle_name: str | None = Field(default=None)
    birth_date: str | None = Field(default=None)
    grade: str | None = Field(default=None)
    school: str | None = Field(default=None)
    city: str | None = Field(default=None)
    role: str = Field(..., pattern=r"^(competitor|jury|admin)$")
    challenge_id: str | None = Field(default=None)
    is_anonymous: bool = False
    jury_challenges: list[str] | None = Field(default=None)


class UpdateUserSchema(BaseModel):
    username: str | None = Field(default=None)
    email: str | None = Field(default=None)
    password: str | None = Field(default=None)
    name: str | None = Field(default=None)
    surname: str | None = Field(default=None)
    middle_name: str | None = Field(default=None)
    birth_date: str | None = Field(default=None)
    grade: str | None = Field(default=None)
    school: str | None = Field(default=None)
    city: str | None = Field(default=None)
    role: str | None = Field(default=None, pattern=r"^(competitor|jury|admin)$")
    challenge_id: str | None = Field(default=None)
    is_anonymous: bool | None = Field(default=None)
    jury_challenges: list[str] | None = Field(default=None)
