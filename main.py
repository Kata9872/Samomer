from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, SQLModel, create_engine, select

from models import Log, LogInput, Tracker, TrackerInput

BASE_DIR = Path(__file__).resolve().parent
engine = create_engine(
    "sqlite:///" + (BASE_DIR / "samomer.db").as_posix(),
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def enable_foreign_keys(connection, _):
    connection.execute("PRAGMA foreign_keys=ON")


@asynccontextmanager
async def lifespan(app):
    SQLModel.metadata.create_all(engine)
    yield


app = FastAPI(title="Самомер", lifespan=lifespan)


def get_session():
    with Session(engine) as session:
        yield session


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    return JSONResponse(status_code=500, content={"detail": "Не удалось сохранить или прочитать данные. Повторите попытку."})


def statistics(tracker, logs, today=None):
    today = today or date.today()
    daily = defaultdict(float)
    for log in logs:
        daily[log.date] += log.value
    start = today if tracker.period == "daily" else today - timedelta(days=today.weekday())
    current = sum(value for day, value in daily.items() if start.isoformat() <= day <= today.isoformat())
    percent = min(100.0, max(0.0, current / tracker.target_value * 100))
    streak = 0
    if tracker.period == "daily":
        threshold = 1 if tracker.type == "boolean" else tracker.target_value
        cursor = today
        if daily.get(cursor.isoformat(), 0) < threshold:
            cursor -= timedelta(days=1)
        while daily.get(cursor.isoformat(), 0) >= threshold:
            streak += 1
            cursor -= timedelta(days=1)
    return {
        "current_value": current,
        "completion_percent": round(percent, 2),
        "streak": streak if tracker.period == "daily" else None,
        "history": [{"date": log.date, "value": log.value} for log in logs],
        "chart": [{"date": day, "value": value} for day, value in sorted(daily.items())],
    }


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/api/trackers")
def list_trackers(session: Session = Depends(get_session)):
    trackers = session.exec(select(Tracker).order_by(Tracker.id)).all()
    logs = session.exec(select(Log).order_by(Log.date, Log.id)).all()
    grouped = defaultdict(list)
    for log in logs:
        grouped[log.tracker_id].append(log)
    result = []
    for tracker in trackers:
        stats = statistics(tracker, grouped[tracker.id])
        result.append({**tracker.model_dump(), **{key: stats[key] for key in ("current_value", "completion_percent", "streak")}})
    return result


@app.post("/api/trackers", status_code=201)
def create_tracker(data: TrackerInput, session: Session = Depends(get_session)):
    if data.type == "boolean" and data.period == "daily" and data.target_value != 1:
        raise HTTPException(400, "Для ежедневного трекера выполнения цель должна быть равна 1.")
    tracker = Tracker.model_validate(data)
    session.add(tracker)
    session.commit()
    session.refresh(tracker)
    return tracker


@app.post("/api/logs", status_code=201)
def create_log(data: LogInput, session: Session = Depends(get_session)):
    tracker = session.get(Tracker, data.tracker_id)
    if tracker is None:
        raise HTTPException(404, "Трекер не найден")
    if tracker.type == "boolean" and data.value not in (0, 1):
        raise HTTPException(400, "Для трекера выполнения допустимы только 0 и 1.")
    if tracker.type in ("counter", "duration", "scale") and data.value < 0:
        raise HTTPException(400, "Значение этого типа трекера не может быть отрицательным.")
    log = Log.model_validate(data)
    session.add(log)
    session.commit()
    session.refresh(log)
    return log


@app.get("/api/trackers/{tracker_id}/stats")
def tracker_stats(tracker_id: int, session: Session = Depends(get_session)):
    tracker = session.get(Tracker, tracker_id)
    if tracker is None:
        raise HTTPException(404, "Трекер не найден")
    logs = session.exec(select(Log).where(Log.tracker_id == tracker_id).order_by(Log.date, Log.id)).all()
    return statistics(tracker, logs)
