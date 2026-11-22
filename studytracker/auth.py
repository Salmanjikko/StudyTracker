"""Авторизация: пароли с солью, блокировка после 5 неудачных попыток."""
import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timedelta

from .errors import LoginError

MAX_ATTEMPTS = 5
LOCK_MINUTES = 5
_ITERATIONS = 200_000
_TS = "%Y-%m-%d %H:%M:%S"


def new_salt():
    return os.urandom(16).hex()


def hash_password(password, salt_hex):
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), _ITERATIONS)
    return digest.hex()


@dataclass(frozen=True)
class User:
    id: int
    login: str
    role: str


class AuthService:
    def __init__(self, db, now=datetime.now):
        self.db = db
        self.now = now

    def login(self, login, password):
        login = (login or "").strip()
        if not login or not password:
            raise LoginError("Введите логин и пароль.", actor=login or None)
        now = self.now()
        conn = self.db.conn

        att = conn.execute(
            "SELECT failures, locked_until FROM login_attempts WHERE login = ?",
            (login,)).fetchone()
        if att and att["locked_until"]:
            until = datetime.strptime(att["locked_until"], _TS)
            if until > now:
                raise LoginError(
                    f"Вход заблокирован до {until:%H:%M:%S}. Попробуйте позже.", actor=login)

        row = conn.execute(
            "SELECT id, login, password_hash, salt, role FROM users WHERE login = ?",
            (login,)).fetchone()
        salt = row["salt"] if row else new_salt()
        ok = hmac.compare_digest(
            hash_password(password, salt), row["password_hash"] if row else "")
        if row and ok:
            with self.db.transaction():
                conn.execute("DELETE FROM login_attempts WHERE login = ?", (login,))
                self.db.log_event(login, "login", "Успешный вход")
            return User(row["id"], row["login"], row["role"])

        failures = (att["failures"] if att else 0) + 1
        locked = None
        if failures >= MAX_ATTEMPTS:
            locked = (now + timedelta(minutes=LOCK_MINUTES)).strftime(_TS)
            failures = 0
        with self.db.transaction():
            conn.execute(
                "INSERT INTO login_attempts (login, failures, locked_until) VALUES (?, ?, ?) "
                "ON CONFLICT(login) DO UPDATE SET failures = excluded.failures, "
                "locked_until = excluded.locked_until",
                (login, failures, locked))
        if locked:
            raise LoginError(
                f"Превышено число попыток входа. Вход заблокирован на {LOCK_MINUTES} минут.",
                actor=login)
        left = MAX_ATTEMPTS - failures
        raise LoginError(f"Неверный логин или пароль. Осталось попыток: {left}.", actor=login)
