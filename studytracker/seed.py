"""Создание таблиц и тестовых данных.

В тестовой базе 30 студентов, 3 формы обучения, 10 дисциплин,
105 оценок и по одной учётной записи каждой роли.

Запуск вручную: python -m studytracker.seed
"""
import random
from pathlib import Path

from .auth import hash_password, new_salt
from .db import (REPORT_CREDIT, REPORT_EXAM, ROLE_DEAN, ROLE_TEACHER, STUDY_FORMS, Database)

USERS = [
    ("dekanat", "dekanat2026", ROLE_DEAN),
    ("teacher", "teacher2026", ROLE_TEACHER),
]

SPECIALTIES = ["09.03.01 Информатика и вычислительная техника", "09.03.04 Программная инженерия"]
GROUPS = [("241-321", 0), ("241-322", 0), ("241-325", 1), ("241-326", 1)]

# (семестр, дисциплина, часы, форма отчётности) для каждой специальности
CURRICULUM = [
    [(1, "Математический анализ", 144, REPORT_EXAM),
     (1, "Программирование", 144, REPORT_EXAM),
     (1, "История России", 72, REPORT_CREDIT),
     (2, "Алгебра и геометрия", 108, REPORT_EXAM),
     (2, "Физика", 108, REPORT_EXAM),
     (2, "Иностранный язык", 72, REPORT_CREDIT),
     (3, "Базы данных", 108, REPORT_EXAM),
     (3, "Операционные системы", 108, REPORT_EXAM)],
    [(1, "Математический анализ", 144, REPORT_EXAM),
     (1, "Программирование", 144, REPORT_EXAM),
     (1, "Физическая культура", 72, REPORT_CREDIT),
     (2, "Алгебра и геометрия", 108, REPORT_EXAM),
     (2, "Иностранный язык", 72, REPORT_CREDIT),
     (2, "Теория вероятностей", 108, REPORT_EXAM),
     (3, "Базы данных", 108, REPORT_EXAM),
     (3, "Операционные системы", 72, REPORT_CREDIT)],
]

LAST_M = ["Иванов", "Петров", "Смирнов", "Кузнецов", "Попов", "Соколов", "Лебедев",
          "Козлов", "Новиков", "Морозов", "Волков", "Орлов", "Захаров", "Павлов", "Семёнов"]
FIRST_M = ["Александр", "Дмитрий", "Максим", "Иван", "Артём", "Михаил", "Никита", "Андрей"]
FIRST_F = ["Анна", "Мария", "Елена", "Ольга", "Екатерина", "Дарья", "Софья", "Алиса"]
MIDDLE_M = ["Александрович", "Сергеевич", "Андреевич", "Игоревич", "Павлович"]
MIDDLE_F = ["Александровна", "Сергеевна", "Андреевна", "Игоревна", "Павловна"]


def seed(db):
    rng = random.Random(2026)
    with db.transaction() as conn:
        for name in SPECIALTIES:
            conn.execute("INSERT INTO specialties (name) VALUES (?)", (name,))
        for name, spec_index in GROUPS:
            conn.execute('INSERT INTO "groups" (name, specialty_id) VALUES (?, ?)',
                         (name, spec_index + 1))

        discipline_ids = {}
        for rows in CURRICULUM:
            for _, name, _, _ in rows:
                if name not in discipline_ids:
                    discipline_ids[name] = conn.execute(
                        "INSERT INTO disciplines (name) VALUES (?)", (name,)).lastrowid
        for spec_index, rows in enumerate(CURRICULUM):
            for semester, name, hours, form in rows:
                conn.execute(
                    "INSERT INTO curriculum (specialty_id, discipline_id, semester, hours, "
                    "report_form) VALUES (?, ?, ?, ?, ?)",
                    (spec_index + 1, discipline_ids[name], semester, hours, form))

        students = []  # (id, admission_year, specialty_index)
        for i in range(30):
            female = i % 2 == 1
            last = LAST_M[i % len(LAST_M)] + ("а" if female else "")
            first = rng.choice(FIRST_F if female else FIRST_M)
            middle = rng.choice(MIDDLE_F if female else MIDDLE_M)
            year = 2023 + i % 3
            group_index = i % len(GROUPS)
            sid = conn.execute(
                "INSERT INTO students (last_name, first_name, middle_name, admission_year, "
                "study_form, group_id) VALUES (?, ?, ?, ?, ?, ?)",
                (last, first, middle, year, STUDY_FORMS[i % 3], group_index + 1)).lastrowid
            students.append((sid, year, GROUPS[group_index][1]))

        # оценки за 1-й семестр у всех и за 2-й у первых пяти студентов (всего 105)
        for n, (sid, adm_year, spec_index) in enumerate(students):
            for semester, name, _, form in CURRICULUM[spec_index]:
                if semester == 1 or (semester == 2 and n < 5):
                    grade = (rng.choice(["2", "3", "3", "4", "4", "5", "5"])
                             if form == REPORT_EXAM
                             else rng.choice(["зачёт", "зачёт", "зачёт", "незачёт"]))
                    conn.execute(
                        "INSERT INTO grades (year, semester, student_id, discipline_id, grade) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (adm_year + (semester - 1) // 2, semester, sid,
                         discipline_ids[name], grade))

        for login, password, role in USERS:
            salt = new_salt()
            conn.execute(
                "INSERT INTO users (login, password_hash, salt, role) VALUES (?, ?, ?, ?)",
                (login, hash_password(password, salt), salt, role))


def create_database(path):
    """Создаёт файл базы данных со схемой и тестовыми данными."""
    db = Database.create(path)
    seed(db)
    return db


if __name__ == "__main__":
    target = Path(__file__).resolve().parent.parent / "data" / "studytracker.db"
    if target.exists():
        print(f"Файл уже существует: {target}")
    else:
        create_database(target).close()
        print(f"База данных создана: {target}")
