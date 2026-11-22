import sqlite3
from datetime import timedelta

import pytest

from studytracker.db import Database, make_backup, restore_latest_backup
from studytracker.errors import (AccessDeniedError, DatabaseUnavailableError,
                                 DuplicateGradeError, GradeOutOfRangeError,
                                 InvalidInputError, LoginError, NotFoundError,
                                 NotInCurriculumError)
from studytracker.hooks import ErrorHandler


def one(db, sql, *params):
    return db.conn.execute(sql, params).fetchone()[0]


def disc_id(db, name):
    return one(db, "SELECT id FROM disciplines WHERE name = ?", name)


def student_in_spec(db, spec_name_prefix):
    return one(db, 'SELECT s.id FROM students s JOIN "groups" g ON g.id = s.group_id '
                   "JOIN specialties sp ON sp.id = g.specialty_id WHERE sp.name LIKE ? "
                   "ORDER BY s.id LIMIT 1", spec_name_prefix + "%")


def grade_data(db, student_id, discipline, semester, grade, year=2025):
    return {"year": year, "semester": semester, "student_id": student_id,
            "discipline_id": disc_id(db, discipline), "grade": grade}


# ---------- тестовые данные ----------

def test_seed_minimum(db):
    assert one(db, "SELECT COUNT(*) FROM students") >= 30
    assert one(db, "SELECT COUNT(DISTINCT study_form) FROM students") == 3
    assert one(db, "SELECT COUNT(*) FROM disciplines") >= 10
    assert one(db, "SELECT COUNT(*) FROM grades") >= 100
    assert one(db, "SELECT COUNT(DISTINCT role) FROM users") == 2


# ---------- подсчёт и данные по дисциплине ----------

def test_count_by_form(dean_svc, db):
    for form in ("дневная", "вечерняя", "заочная"):
        expected = one(db, "SELECT COUNT(*) FROM students WHERE study_form = ?", form)
        assert dean_svc.students.count_by_form(form) == expected


def test_discipline_info(dean_svc, db):
    rows = dean_svc.curriculum.discipline_info(disc_id(db, "Математический анализ"))
    assert {(r["hours"], r["report_form"]) for r in rows} == {(144, "экзамен")}


# ---------- студенты и учебный план ----------

def student_data(**kw):
    data = {"last_name": "Тестов", "first_name": "Тест", "middle_name": "Тестович",
            "group_id": 1, "admission_year": "2025", "study_form": "дневная"}
    data.update(kw)
    return data


def test_add_and_update_student(dean_svc, db):
    sid = dean_svc.students.add(student_data())
    dean_svc.students.update(sid, student_data(last_name="Иванов-Тестов"))
    assert dean_svc.students.get(sid)["last_name"] == "Иванов-Тестов"


def test_search_students_case_insensitive_cyrillic(dean_svc):
    rows = dean_svc.students.list(last_name="иван")
    assert rows and all("иван" in r["last_name"].lower() for r in rows)


def test_add_and_update_curriculum(dean_svc, db):
    cid = dean_svc.curriculum.add({"specialty_id": 1, "discipline": "Новая дисциплина",
                                   "semester": "4", "hours": "90", "report_form": "зачёт"})
    dean_svc.curriculum.update(cid, {"specialty_id": 1, "discipline": "Новая дисциплина",
                                     "semester": "4", "hours": "120", "report_form": "экзамен"})
    assert dean_svc.curriculum.get(cid)["hours"] == 120


# ---------- журнал успеваемости ----------

def test_add_and_update_grade_and_log(teacher_svc, db):
    sid = student_in_spec(db, "09.03.01")
    gid = teacher_svc.grades.add(grade_data(db, sid, "Базы данных", 3, "4"))
    teacher_svc.grades.update(gid, grade_data(db, sid, "Базы данных", 3, "5"))
    assert teacher_svc.grades.get(gid)["grade"] == "5"
    events = [r["event"] for r in db.conn.execute("SELECT event FROM event_log")]
    assert "grade_add" in events and "grade_update" in events


def test_credit_grade_normalized(teacher_svc, db):
    # У специальности «Программная инженерия» «Операционные системы» в 3-м семестре — зачёт.
    sid = student_in_spec(db, "09.03.04")
    gid = teacher_svc.grades.add(grade_data(db, sid, "Операционные системы", 3, "Зачет"))
    assert teacher_svc.grades.get(gid)["grade"] == "зачёт"


# ---------- хуки ST001–ST008 ----------

def test_st001_grade_out_of_range(teacher_svc, db):
    sid = student_in_spec(db, "09.03.01")
    with pytest.raises(GradeOutOfRangeError) as exc:
        teacher_svc.grades.add(grade_data(db, sid, "Базы данных", 3, "6"))
    assert exc.value.code == "ST001"
    with pytest.raises(GradeOutOfRangeError):  # для зачёта оценка 5 недопустима
        teacher_svc.grades.add(grade_data(db, sid, "Иностранный язык", 2, "5"))


def test_st002_duplicate_grade(teacher_svc, db):
    sid = student_in_spec(db, "09.03.01")
    teacher_svc.grades.add(grade_data(db, sid, "Базы данных", 3, "4"))
    with pytest.raises(DuplicateGradeError) as exc:
        teacher_svc.grades.add(grade_data(db, sid, "Базы данных", 3, "5"))
    assert exc.value.code == "ST002"


def test_st003_not_found(teacher_svc, db):
    data = grade_data(db, 99999, "Базы данных", 3, "4")
    with pytest.raises(NotFoundError) as exc:
        teacher_svc.grades.add(data)
    assert exc.value.code == "ST003" and exc.value.message == "Данные не найдены"
    sid = student_in_spec(db, "09.03.01")
    data = grade_data(db, sid, "Базы данных", 3, "4")
    data["discipline_id"] = 99999
    with pytest.raises(NotFoundError):
        teacher_svc.grades.add(data)


@pytest.mark.parametrize("bad, field", [
    ({"last_name": "  "}, "last_name"),
    ({"first_name": ""}, "first_name"),
    ({"admission_year": "1999"}, "admission_year"),
    ({"admission_year": "2027"}, "admission_year"),
    ({"admission_year": "abc"}, "admission_year"),
])
def test_st004_invalid_student(dean_svc, bad, field):
    with pytest.raises(InvalidInputError) as exc:
        dean_svc.students.add(student_data(**bad))
    assert exc.value.code == "ST004" and exc.value.field == field


def test_st005_not_in_curriculum(teacher_svc, db):
    sid = student_in_spec(db, "09.03.01")  # у этой специальности нет «Физической культуры»
    with pytest.raises(NotInCurriculumError) as exc:
        teacher_svc.grades.add(grade_data(db, sid, "Физическая культура", 1, "зачёт"))
    assert exc.value.code == "ST005"


def test_st006_role_restrictions(dean_svc, teacher_svc, db):
    with pytest.raises(AccessDeniedError) as exc:
        teacher_svc.curriculum.add({"specialty_id": 1, "discipline": "X", "semester": "1",
                                    "hours": "10", "report_form": "зачёт"})
    assert exc.value.code == "ST006"
    with pytest.raises(AccessDeniedError):
        teacher_svc.students.add(student_data())
    sid = student_in_spec(db, "09.03.01")
    with pytest.raises(AccessDeniedError):
        dean_svc.grades.add(grade_data(db, sid, "Базы данных", 3, "4"))


def test_st006_is_logged_by_handler(db, teacher_svc, teacher):
    handler = ErrorHandler(db, lambda: teacher)
    try:
        teacher_svc.students.add(student_data())
    except Exception as exc:
        err = handler.handle(exc)
    assert err.code == "ST006"
    row = db.conn.execute("SELECT login, event FROM event_log ORDER BY id DESC LIMIT 1").fetchone()
    assert (row["login"], row["event"]) == ("teacher", "error:ST006")


def test_st007_wrong_login_and_lockout(auth, clock, db):
    for left in (4, 3, 2, 1):
        with pytest.raises(LoginError) as exc:
            auth.login("teacher", "wrong")
        assert exc.value.code == "ST007" and f"Осталось попыток: {left}" in exc.value.message
    with pytest.raises(LoginError) as exc:
        auth.login("teacher", "wrong")           # 5-я ошибка подряд
    assert "заблокирован" in exc.value.message
    with pytest.raises(LoginError):
        auth.login("teacher", "teacher2026")     # верный пароль, но вход заблокирован
    clock.value += timedelta(minutes=5, seconds=1)
    assert auth.login("teacher", "teacher2026").role == "teacher"


def test_unknown_login_rejected(auth):
    with pytest.raises(LoginError):
        auth.login("nobody", "x")


def test_passwords_stored_as_salted_hash(db):
    rows = db.conn.execute("SELECT password_hash, salt FROM users").fetchall()
    assert len({r["salt"] for r in rows}) == 2
    assert all("2026" not in r["password_hash"] for r in rows)


def test_st008_missing_and_corrupted_file(tmp_path):
    with pytest.raises(DatabaseUnavailableError) as exc:
        Database.open(tmp_path / "none.db")
    assert exc.value.code == "ST008"
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a sqlite database" * 100)
    with pytest.raises(DatabaseUnavailableError):
        Database.open(bad)


# ---------- транзакции, журнал, копии ----------

def test_failed_operation_leaves_no_trace(teacher_svc, db, teacher):
    before = one(db, "SELECT COUNT(*) FROM grades")
    sid = student_in_spec(db, "09.03.01")
    with pytest.raises(GradeOutOfRangeError):
        teacher_svc.grades.add(grade_data(db, sid, "Базы данных", 3, "9"))
    assert one(db, "SELECT COUNT(*) FROM grades") == before


def test_transaction_rolls_back(db):
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.conn.execute("INSERT INTO specialties (name) VALUES ('temp')")
            raise RuntimeError
    assert one(db, "SELECT COUNT(*) FROM specialties WHERE name = 'temp'") == 0


def test_login_is_logged(db, auth):
    auth.login("dekanat", "dekanat2026")
    assert one(db, "SELECT COUNT(*) FROM event_log WHERE event = 'login'") == 1


def test_foreign_keys_enforced(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute("INSERT INTO grades (year, semester, student_id, discipline_id, grade) "
                        "VALUES (2025, 1, 9999, 1, '5')")


def test_backup_once_a_day_and_keep_five(db, tmp_path):
    from datetime import date
    backup_dir = tmp_path / "backup"
    first = make_backup(db.path, backup_dir, today=date(2026, 11, 1))
    assert first and first.exists()
    assert make_backup(db.path, backup_dir, today=date(2026, 11, 1)) is None
    for day in range(2, 9):
        make_backup(db.path, backup_dir, today=date(2026, 11, day))
    names = sorted(p.name for p in backup_dir.glob("studytracker_*.db"))
    assert len(names) == 5 and names[-1] == "studytracker_20261108.db"


def test_restore_from_backup(db, tmp_path):
    from datetime import date
    backup_dir = tmp_path / "backup"
    make_backup(db.path, backup_dir, today=date(2026, 11, 1))
    db.close()
    db.path.write_bytes(b"broken" * 100)
    restore_latest_backup(db.path, backup_dir)
    restored = Database.open(db.path)
    assert one(restored, "SELECT COUNT(*) FROM students") == 30
    restored.close()
