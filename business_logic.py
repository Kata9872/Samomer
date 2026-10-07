from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
import sys

from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, SQLModel, create_engine, select

from models import Log, LogInput, Tracker, TrackerInput


class DataError(Exception):
    pass


class Store:
    def __init__(self, db_path=None):
        if db_path is not None:
            path = Path(db_path)
        else:
            app_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
            path = app_dir / "trackall.db"
        self.engine = create_engine("sqlite:///" + path.resolve().as_posix())

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        try:
            SQLModel.metadata.create_all(self.engine)
        except SQLAlchemyError as exc:
            self.engine.dispose()
            raise DataError("Локальная база данных недоступна. Проверьте файл trackall.db и перезапустите приложение.") from exc

    def get_trackers(self):
        try:
            with Session(self.engine) as session:
                trackers = session.exec(select(Tracker).order_by(Tracker.id)).all()
                logs = session.exec(select(Log).order_by(Log.date, Log.id)).all()
                grouped = defaultdict(list)
                for log in logs:
                    grouped[log.tracker_id].append(log)
                return [{**tracker.model_dump(), **self._stats(tracker, grouped[tracker.id], include_history=False)} for tracker in trackers]
        except SQLAlchemyError as exc:
            raise DataError("Не удалось прочитать локальную базу данных. Проверьте trackall.db.") from exc

    def create_tracker(self, name, type, target_value, period, unit):
        data = TrackerInput.model_validate(dict(name=name, type=type, target_value=target_value, period=period, unit=unit))
        if data.type == "boolean" and data.target_value != 1:
            raise ValueError("Для трекера выполнения цель должна быть равна 1.")
        try:
            with Session(self.engine) as session:
                tracker = Tracker(**data.model_dump())
                session.add(tracker)
                session.commit()
                session.refresh(tracker)
                return tracker
        except SQLAlchemyError as exc:
            raise DataError("Не удалось сохранить трекер. Проверьте файл trackall.db.") from exc

    def add_log(self, tracker_id, value, date):
        data = LogInput.model_validate(dict(tracker_id=tracker_id, value=value, date=date))
        try:
            with Session(self.engine) as session:
                tracker = session.get(Tracker, data.tracker_id)
                if tracker is None:
                    raise ValueError("Трекер не найден.")
                if tracker.type == "boolean" and data.value not in (0, 1):
                    raise ValueError("Для выполнения допустимы только 0 и 1.")
                if tracker.type in ("counter", "duration", "scale") and data.value < 0:
                    raise ValueError("Значение не может быть отрицательным.")
                log = Log(**data.model_dump())
                session.add(log)
                session.commit()
                logs = session.exec(select(Log).where(Log.tracker_id == tracker.id)).all()
                return {**tracker.model_dump(), **self._stats(tracker, logs, include_history=False)}
        except SQLAlchemyError as exc:
            raise DataError("Не удалось сохранить значение. Проверьте файл trackall.db.") from exc

    def get_stats(self, tracker_id):
        try:
            tracker_id = int(tracker_id)
        except (ValueError, TypeError) as exc:
            raise ValueError("Некорректный номер трекера.") from exc
        try:
            with Session(self.engine) as session:
                tracker = session.get(Tracker, tracker_id)
                if tracker is None:
                    raise ValueError("Трекер не найден.")
                logs = session.exec(select(Log).where(Log.tracker_id == tracker_id).order_by(Log.date, Log.id)).all()
                return {**tracker.model_dump(), **self._stats(tracker, logs, include_history=True)}
        except SQLAlchemyError as exc:
            raise DataError("Не удалось получить статистику. Проверьте файл trackall.db.") from exc

    @staticmethod
    def _stats(tracker, logs, include_history, today=None):
        today = today or date.today()
        daily = defaultdict(float)
        for log in logs:
            daily[log.date] += log.value
        start = today if tracker.period == "daily" else today - timedelta(days=today.weekday())
        total = sum(value for day, value in daily.items() if start.isoformat() <= day <= today.isoformat())
        period_target = tracker.target_value * (7 if tracker.period == "weekly" else 1)
        percent = min(100.0, max(0.0, total / period_target * 100))
        streak = None
        if tracker.period == "daily":
            streak = 0
            cursor = today
            threshold = 1 if tracker.type == "boolean" else tracker.target_value
            if daily.get(cursor.isoformat(), 0) < threshold:
                cursor -= timedelta(days=1)
            while daily.get(cursor.isoformat(), 0) >= threshold:
                streak += 1
                cursor -= timedelta(days=1)
        result = {"current_value": total, "period_target": period_target, "completion_percent": round(percent, 2), "streak": streak}
        if include_history:
            result["history"] = [{"date": log.date, "value": log.value} for log in logs]
            result["by_date"] = [{"date": day, "value": value} for day, value in sorted(daily.items())]
        return result
