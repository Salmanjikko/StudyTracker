"""Запуск приложения: открытие базы, резервная копия, восстановление."""
import sqlite3
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

from .db import Database, list_backups, make_backup, restore_latest_backup
from .errors import DatabaseUnavailableError
from .gui import App
from .seed import create_database


def _startup_log(base, message):
    """Пишет ошибку в текстовый файл, если базу открыть не удалось."""
    try:
        (base / "data").mkdir(exist_ok=True)
        with open(base / "data" / "startup_errors.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} ST008 {message}\n")
    except OSError:
        pass


def open_database(base):
    """Открывает базу. При ошибке ST008 предлагает повторить или восстановить копию."""
    db_path = base / "data" / "studytracker.db"
    backup_dir = base / "backup"
    while True:
        try:
            if not db_path.exists() and not list_backups(backup_dir):
                create_database(db_path).close()  # первый запуск
            db = Database.open(db_path)
            break
        except DatabaseUnavailableError as err:
            _startup_log(base, err.message)
            answer = messagebox.askyesnocancel(
                "Ошибка ST008",
                f"{err.message}\n\nДа — повторить попытку\n"
                "Нет — восстановить базу из последней резервной копии\n"
                "Отмена — выйти из программы")
            if answer is None:
                return None
            if answer is False:
                try:
                    restore_latest_backup(db_path, backup_dir)
                except (DatabaseUnavailableError, OSError) as exc:
                    messagebox.showerror("Ошибка ST008", str(exc))
    try:
        make_backup(db_path, backup_dir)
    except (OSError, sqlite3.Error) as exc:
        _startup_log(base, f"Не удалось создать резервную копию: {exc}")
    return db


def main():
    base = Path(__file__).resolve().parent.parent
    root = tk.Tk()
    root.withdraw()
    db = open_database(base)
    if db is None:
        root.destroy()
        return
    root.deiconify()
    App(root, db)

    def on_close():
        db.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
