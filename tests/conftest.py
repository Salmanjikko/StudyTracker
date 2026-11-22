from datetime import datetime

import pytest

from studytracker.auth import AuthService
from studytracker.seed import create_database
from studytracker.services import Services


@pytest.fixture
def db(tmp_path):
    database = create_database(tmp_path / "test.db")
    yield database
    database.close()


class Clock:
    def __init__(self):
        self.value = datetime(2026, 11, 20, 12, 0, 0)

    def __call__(self):
        return self.value


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def auth(db, clock):
    return AuthService(db, now=clock)


@pytest.fixture
def dean(auth):
    return auth.login("dekanat", "dekanat2026")


@pytest.fixture
def teacher(auth):
    return auth.login("teacher", "teacher2026")


@pytest.fixture
def dean_svc(db, dean):
    return Services(db, dean)


@pytest.fixture
def teacher_svc(db, teacher):
    return Services(db, teacher)
