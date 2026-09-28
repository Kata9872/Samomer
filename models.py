from datetime import date as Date
from typing import Literal

from pydantic import ConfigDict, Field as InputField, field_validator
from sqlmodel import Field, SQLModel


class TrackerInput(SQLModel):
    model_config = ConfigDict(str_strip_whitespace=True, allow_inf_nan=False)

    name: str = Field(min_length=1, max_length=50)
    type: Literal["boolean", "counter", "duration", "numeric", "scale"]
    target_value: float = Field(gt=0)
    period: Literal["daily", "weekly"]
    unit: str = Field(min_length=1, max_length=20)


class Tracker(TrackerInput, table=True):
    id: int | None = Field(default=None, primary_key=True)
    type: str
    period: str


class LogInput(SQLModel):
    model_config = ConfigDict(allow_inf_nan=False)

    tracker_id: int = Field(gt=0)
    value: float
    date: str = InputField(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("date")
    @classmethod
    def valid_date(cls, value: str) -> str:
        if Date.fromisoformat(value) > Date.today():
            raise ValueError("Дата не может быть в будущем")
        return value


class Log(LogInput, table=True):
    id: int | None = Field(default=None, primary_key=True)
    tracker_id: int = Field(foreign_key="tracker.id")
