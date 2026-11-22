"""Общий обработчик ошибок."""
import sqlite3

from .errors import AppError, DatabaseUnavailableError


class ErrorHandler:
    """Откатывает операцию, пишет событие в журнал и возвращает AppError."""

    def __init__(self, db, current_user=lambda: None):
        self.db = db
        self.current_user = current_user

    def handle(self, exc):
        if isinstance(exc, AppError):
            err = exc
        elif isinstance(exc, sqlite3.Error):
            err = DatabaseUnavailableError(
                "Не удалось выполнить операцию с базой данных. Повторите попытку.")
        else:
            err = AppError()
        try:
            self.db.rollback()
            user = self.current_user()
            actor = err.actor or (user.login if user else None)
            self.db.log_event(actor, "error:" + err.code, err.message)
        except Exception:
            # если журнал недоступен, программа всё равно продолжает работать
            pass
        return err
