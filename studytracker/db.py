"""Работа с базой SQLite: схема, подключение, транзакции, резервные копии."""
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from .errors import DatabaseUnavailableError

STUDY_FORMS = ("дневная", "вечерняя", "заочная")
REPORT_EXAM = "экзамен"
REPORT_CREDIT = "зачёт"
REPORT_FORMS = (REPORT_EXAM, REPORT_CREDIT)
ROLE_DEAN = "dean"
ROLE_TEACHER = "teacher"
ROLE_LABELS = {ROLE_DEAN: "Сотрудник деканата", ROLE_TEACHER: "Преподаватель"}

BACKUP_KEEP = 5

SCHEMA = """
CREATE TABLE specialties (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE "groups" (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    specialty_id INTEGER NOT NULL REFERENCES specialties(id)
);
CREATE TABLE students (
    id             INTEGER PRIMARY KEY,
    last_name      TEXT NOT NULL CHECK (length(trim(last_name)) > 0),
    first_name     TEXT NOT NULL CHECK (length(trim(first_name)) > 0),
    middle_name    TEXT NOT NULL DEFAULT '',
    admission_year INTEGER NOT NULL CHECK (admission_year BETWEEN 2000 AND 2026),
    study_form     TEXT NOT NULL CHECK (study_form IN ('дневная', 'вечерняя', 'заочная')),
    group_id       INTEGER NOT NULL REFERENCES "groups"(id)
);
CREATE INDEX idx_students_last_name ON students(last_name);
CREATE TABLE disciplines (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE curriculum (
    id            INTEGER PRIMARY KEY,
    specialty_id  INTEGER NOT NULL REFERENCES specialties(id),
    discipline_id INTEGER NOT NULL REFERENCES disciplines(id),
    semester      INTEGER NOT NULL CHECK (semester BETWEEN 1 AND 12),
    hours         INTEGER NOT NULL CHECK (hours > 0),
    report_form   TEXT NOT NULL CHECK (report_form IN ('экзамен', 'зачёт')),
    UNIQUE (specialty_id, discipline_id, semester)
);
CREATE TABLE grades (
    id            INTEGER PRIMARY KEY,
    year          INTEGER NOT NULL CHECK (year BETWEEN 2000 AND 2100),
    semester      INTEGER NOT NULL CHECK (semester BETWEEN 1 AND 12),
    student_id    INTEGER NOT NULL REFERENCES students(id),
    discipline_id INTEGER NOT NULL REFERENCES disciplines(id),
    grade         TEXT NOT NULL CHECK (grade IN ('2', '3', '4', '5', 'зачёт', 'незачёт')),
    UNIQUE (student_id, discipline_id, semester)
);
CREATE INDEX idx_grades_student ON grades(student_id);
CREATE TABLE users (
    id            INTEGER PRIMARY KEY,
    login         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('dean', 'teacher'))
);
CREATE TABLE login_attempts (
    login        TEXT PRIMARY KEY,
    failures     INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT
);
CREATE TABLE event_log (
    id      INTEGER PRIMARY KEY,
    ts      TEXT NOT NULL,
    login   TEXT,
    event   TEXT NOT NULL,
    details TEXT
);
"""


def _py_lower(value):
    # LIKE в SQLite игнорирует регистр только у латиницы, поэтому для кириллицы своя функция
    return value.lower() if isinstance(value, str) else value


def _connect(path):
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=3)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.create_function("py_lower", 1, _py_lower)
    return conn


class Database:
    def __init__(self, conn, path):
        self.conn = conn
        self.path = Path(path)

    @classmethod
    def open(cls, path):
        """Открывает существующую базу, при проблемах выбрасывает ST008."""
        path = Path(path)
        if not path.is_file():
            raise DatabaseUnavailableError(f"Файл базы данных не найден: {path}")
        conn = None
        try:
            conn = _connect(path)
            if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("quick_check failed")
            has_users = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
            if has_users is None:
                raise sqlite3.DatabaseError("schema missing")
        except sqlite3.OperationalError as exc:
            if conn:
                conn.close()
            if "locked" in str(exc).lower():
                raise DatabaseUnavailableError(
                    "Файл базы данных занят другой программой.") from exc
            raise DatabaseUnavailableError("Не удалось открыть файл базы данных.") from exc
        except sqlite3.DatabaseError as exc:
            if conn:
                conn.close()
            raise DatabaseUnavailableError("Файл базы данных повреждён.") from exc
        return cls(conn, path)

    @classmethod
    def create(cls, path):
        """Создаёт новую пустую базу со схемой."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = _connect(path)
        conn.executescript(SCHEMA)
        return cls(conn, path)

    def close(self):
        self.conn.close()

    @contextmanager
    def transaction(self):
        """Каждая операция записи выполняется в одной транзакции."""
        self.conn.execute("BEGIN")
        try:
            yield self.conn
            self.conn.execute("COMMIT")
        except sqlite3.Error as exc:
            self.rollback()
            raise DatabaseUnavailableError(
                "Не удалось сохранить данные. Повторите попытку.") from exc
        except BaseException:
            self.rollback()
            raise

    def rollback(self):
        if self.conn.in_transaction:
            self.conn.execute("ROLLBACK")

    def log_event(self, login, event, details=""):
        self.conn.execute(
            "INSERT INTO event_log (ts, login, event, details) VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(sep=" ", timespec="seconds"), login, event, details))


def make_backup(db_path, backup_dir, keep=BACKUP_KEEP, today=None):
    """Копирует базу в backup/ не чаще раза в сутки, хранит последние keep копий."""
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    today = today or date.today()
    target = backup_dir / f"studytracker_{today:%Y%m%d}.db"
    if target.exists():
        return None
    tmp = target.with_suffix(".tmp")
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(tmp))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    tmp.replace(target)
    for old in sorted(backup_dir.glob("studytracker_*.db"))[:-keep]:
        old.unlink()
    return target


def list_backups(backup_dir):
    return sorted(Path(backup_dir).glob("studytracker_*.db"))


def restore_latest_backup(db_path, backup_dir):
    """Заменяет файл базы последней копией; испорченный файл сохраняется как .broken."""
    backups = list_backups(backup_dir)
    if not backups:
        raise DatabaseUnavailableError("Резервных копий нет, восстановить базу нельзя.")
    db_path = Path(db_path)
    if db_path.exists():
        db_path.replace(db_path.with_suffix(".broken"))
    shutil.copy2(backups[-1], db_path)
    return backups[-1]
