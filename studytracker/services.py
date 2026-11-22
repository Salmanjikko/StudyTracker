"""Логика работы со студентами, учебным планом и журналом успеваемости.

Права ролей (ST006) и значения (ST001–ST005) проверяются здесь, до записи в базу.
"""
from .db import (REPORT_CREDIT, REPORT_EXAM, REPORT_FORMS, ROLE_DEAN, ROLE_TEACHER,
                 STUDY_FORMS)
from .errors import (AccessDeniedError, DuplicateGradeError, GradeOutOfRangeError,
                     InvalidInputError, NotFoundError, NotInCurriculumError)

MIN_ADMISSION_YEAR, MAX_ADMISSION_YEAR = 2000, 2026


def _text(value, field, label, required=True):
    s = "" if value is None else str(value).strip()
    if required and not s:
        raise InvalidInputError(f"Поле «{label}» не заполнено.", field)
    return s


def _int(value, field, label, lo, hi):
    try:
        n = int(str(value).strip())
    except (ValueError, TypeError):
        raise InvalidInputError(f"Поле «{label}» должно быть целым числом.", field) from None
    if not lo <= n <= hi:
        raise InvalidInputError(f"Поле «{label}»: допустимы значения от {lo} до {hi}.", field)
    return n


def _choice(value, allowed, field, label):
    if value not in allowed:
        raise InvalidInputError(f"Поле «{label}»: выберите значение из списка.", field)
    return value


class _Service:
    def __init__(self, db, user):
        self.db = db
        self.user = user

    def _require(self, role, action):
        if self.user is None or self.user.role != role:
            raise AccessDeniedError(f"Действие недоступно для вашей роли: {action}.")


class StudentService(_Service):
    def groups(self):
        return self.db.conn.execute(
            'SELECT id, name FROM "groups" ORDER BY name').fetchall()

    def list(self, last_name="", group_id=None):
        sql = ("SELECT s.id, s.last_name, s.first_name, s.middle_name, s.admission_year, "
               "s.study_form, s.group_id, g.name AS group_name "
               'FROM students s JOIN "groups" g ON g.id = s.group_id WHERE 1 = 1')
        params = []
        q = (last_name or "").strip().lower()
        if q:
            q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            sql += " AND py_lower(s.last_name) LIKE ? ESCAPE '\\'"
            params.append(f"%{q}%")
        if group_id is not None:
            sql += " AND s.group_id = ?"
            params.append(group_id)
        sql += " ORDER BY s.last_name, s.first_name, s.id"
        return self.db.conn.execute(sql, params).fetchall()

    def get(self, student_id):
        row = self.db.conn.execute(
            "SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        if row is None:
            raise NotFoundError()
        return row

    def _validate(self, data):
        last = _text(data.get("last_name"), "last_name", "Фамилия")
        first = _text(data.get("first_name"), "first_name", "Имя")
        middle = _text(data.get("middle_name"), "middle_name", "Отчество", required=False)
        year = _int(data.get("admission_year"), "admission_year", "Год поступления",
                    MIN_ADMISSION_YEAR, MAX_ADMISSION_YEAR)
        form = _choice(data.get("study_form"), STUDY_FORMS, "study_form", "Форма обучения")
        group_id = data.get("group_id")
        if group_id is None:
            raise InvalidInputError("Поле «Группа»: выберите значение из списка.", "group_id")
        if self.db.conn.execute(
                'SELECT 1 FROM "groups" WHERE id = ?', (group_id,)).fetchone() is None:
            raise NotFoundError(field="group_id")
        return last, first, middle, year, form, group_id

    def add(self, data):
        self._require(ROLE_DEAN, "добавление студента")
        values = self._validate(data)
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO students (last_name, first_name, middle_name, admission_year, "
                "study_form, group_id) VALUES (?, ?, ?, ?, ?, ?)", values)
            self.db.log_event(self.user.login, "student_add", f"id={cur.lastrowid}")
            return cur.lastrowid

    def update(self, student_id, data):
        self._require(ROLE_DEAN, "изменение данных студента")
        self.get(student_id)
        values = self._validate(data)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE students SET last_name = ?, first_name = ?, middle_name = ?, "
                "admission_year = ?, study_form = ?, group_id = ? WHERE id = ?",
                values + (student_id,))
            self.db.log_event(self.user.login, "student_update", f"id={student_id}")

    def count_by_form(self, form):
        """Число студентов выбранной формы обучения."""
        _choice(form, STUDY_FORMS, "study_form", "Форма обучения")
        return self.db.conn.execute(
            "SELECT COUNT(*) FROM students WHERE study_form = ?", (form,)).fetchone()[0]


class CurriculumService(_Service):
    def specialties(self):
        return self.db.conn.execute("SELECT id, name FROM specialties ORDER BY name").fetchall()

    def disciplines(self):
        return self.db.conn.execute("SELECT id, name FROM disciplines ORDER BY name").fetchall()

    def list(self):
        return self.db.conn.execute(
            "SELECT c.id, sp.name AS specialty, d.name AS discipline, c.semester, c.hours, "
            "c.report_form FROM curriculum c "
            "JOIN specialties sp ON sp.id = c.specialty_id "
            "JOIN disciplines d ON d.id = c.discipline_id "
            "ORDER BY sp.name, c.semester, d.name").fetchall()

    def get(self, curriculum_id):
        row = self.db.conn.execute(
            "SELECT c.*, d.name AS discipline FROM curriculum c "
            "JOIN disciplines d ON d.id = c.discipline_id WHERE c.id = ?",
            (curriculum_id,)).fetchone()
        if row is None:
            raise NotFoundError()
        return row

    def _validate(self, data, curriculum_id=None):
        spec_id = data.get("specialty_id")
        if spec_id is None:
            raise InvalidInputError("Поле «Специальность»: выберите значение из списка.",
                                    "specialty_id")
        if self.db.conn.execute(
                "SELECT 1 FROM specialties WHERE id = ?", (spec_id,)).fetchone() is None:
            raise NotFoundError(field="specialty_id")
        name = _text(data.get("discipline"), "discipline", "Дисциплина")
        semester = _int(data.get("semester"), "semester", "Семестр", 1, 12)
        hours = _int(data.get("hours"), "hours", "Количество часов", 1, 10000)
        form = _choice(data.get("report_form"), REPORT_FORMS, "report_form", "Форма отчётности")
        return spec_id, name, semester, hours, form

    def _discipline_id(self, name):
        row = self.db.conn.execute(
            "SELECT id FROM disciplines WHERE name = ?", (name,)).fetchone()
        if row:
            return row["id"]
        return self.db.conn.execute(
            "INSERT INTO disciplines (name) VALUES (?)", (name,)).lastrowid

    def _save(self, curriculum_id, data):
        spec_id, name, semester, hours, form = self._validate(data, curriculum_id)
        with self.db.transaction() as conn:
            disc_id = self._discipline_id(name)
            dup = conn.execute(
                "SELECT id FROM curriculum WHERE specialty_id = ? AND discipline_id = ? "
                "AND semester = ? AND id IS NOT ?",
                (spec_id, disc_id, semester, curriculum_id)).fetchone()
            if dup:
                raise InvalidInputError(
                    "Такая строка учебного плана уже есть (специальность, дисциплина, семестр).",
                    "discipline")
            if curriculum_id is None:
                cur = conn.execute(
                    "INSERT INTO curriculum (specialty_id, discipline_id, semester, hours, "
                    "report_form) VALUES (?, ?, ?, ?, ?)", (spec_id, disc_id, semester, hours, form))
                curriculum_id = cur.lastrowid
                event = "curriculum_add"
            else:
                conn.execute(
                    "UPDATE curriculum SET specialty_id = ?, discipline_id = ?, semester = ?, "
                    "hours = ?, report_form = ? WHERE id = ?",
                    (spec_id, disc_id, semester, hours, form, curriculum_id))
                event = "curriculum_update"
            self.db.log_event(self.user.login, event, f"id={curriculum_id}")
            return curriculum_id

    def add(self, data):
        self._require(ROLE_DEAN, "добавление строки учебного плана")
        return self._save(None, data)

    def update(self, curriculum_id, data):
        self._require(ROLE_DEAN, "изменение учебного плана")
        self.get(curriculum_id)
        return self._save(curriculum_id, data)

    def discipline_info(self, discipline_id):
        """Часы и форма отчётности выбранной дисциплины."""
        if discipline_id is None or self.db.conn.execute(
                "SELECT 1 FROM disciplines WHERE id = ?", (discipline_id,)).fetchone() is None:
            raise NotFoundError()
        rows = self.db.conn.execute(
            "SELECT sp.name AS specialty, c.semester, c.hours, c.report_form "
            "FROM curriculum c JOIN specialties sp ON sp.id = c.specialty_id "
            "WHERE c.discipline_id = ? ORDER BY sp.name, c.semester",
            (discipline_id,)).fetchall()
        if not rows:
            raise NotFoundError()
        return rows


class GradeService(_Service):
    def list(self):
        return self.db.conn.execute(
            "SELECT gr.id, gr.year, gr.semester, "
            "s.last_name || ' ' || s.first_name || ' ' || s.middle_name AS student, "
            'g.name AS group_name, d.name AS discipline, gr.grade '
            "FROM grades gr JOIN students s ON s.id = gr.student_id "
            'JOIN "groups" g ON g.id = s.group_id '
            "JOIN disciplines d ON d.id = gr.discipline_id "
            "ORDER BY gr.year DESC, gr.semester, s.last_name, d.name").fetchall()

    def get(self, grade_id):
        row = self.db.conn.execute("SELECT * FROM grades WHERE id = ?", (grade_id,)).fetchone()
        if row is None:
            raise NotFoundError()
        return row

    @staticmethod
    def _check_grade(raw, report_form):
        g = (raw or "").strip().lower().replace("ё", "е")
        if report_form == REPORT_EXAM:
            if g in ("2", "3", "4", "5"):
                return g
            raise GradeOutOfRangeError("Для экзамена допустима оценка от 2 до 5.", "grade")
        if g == "зачет":
            return REPORT_CREDIT
        if g == "незачет":
            return "незачёт"
        raise GradeOutOfRangeError(
            "Для зачёта допустимо значение «зачёт» или «незачёт».", "grade")

    def _validate(self, data, grade_id=None):
        conn = self.db.conn
        year = _int(data.get("year"), "year", "Год", 2000, 2100)
        semester = _int(data.get("semester"), "semester", "Семестр", 1, 12)
        student = conn.execute(
            'SELECT s.id, g.specialty_id FROM students s JOIN "groups" g ON g.id = s.group_id '
            "WHERE s.id = ?", (data.get("student_id"),)).fetchone()
        if student is None:
            raise NotFoundError(field="student_id")
        disc = conn.execute(
            "SELECT id, name FROM disciplines WHERE id = ?",
            (data.get("discipline_id"),)).fetchone()
        if disc is None:
            raise NotFoundError(field="discipline_id")
        plan = conn.execute(
            "SELECT report_form FROM curriculum "
            "WHERE specialty_id = ? AND discipline_id = ? AND semester = ?",
            (student["specialty_id"], disc["id"], semester)).fetchone()
        if plan is None:
            raise NotInCurriculumError(
                f"Дисциплины «{disc['name']}» нет в учебном плане специальности студента "
                f"в семестре {semester}. Оценка не добавлена.", "discipline_id")
        grade = self._check_grade(data.get("grade"), plan["report_form"])
        if conn.execute(
                "SELECT 1 FROM grades WHERE student_id = ? AND discipline_id = ? "
                "AND semester = ? AND id IS NOT ?",
                (student["id"], disc["id"], semester, grade_id)).fetchone():
            raise DuplicateGradeError()
        return year, semester, student["id"], disc["id"], grade

    def add(self, data):
        self._require(ROLE_TEACHER, "добавление оценки")
        year, semester, student_id, disc_id, grade = self._validate(data)
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO grades (year, semester, student_id, discipline_id, grade) "
                "VALUES (?, ?, ?, ?, ?)", (year, semester, student_id, disc_id, grade))
            self.db.log_event(
                self.user.login, "grade_add",
                f"id={cur.lastrowid}; student_id={student_id}; discipline_id={disc_id}; "
                f"semester={semester}; grade={grade}")
            return cur.lastrowid

    def update(self, grade_id, data):
        self._require(ROLE_TEACHER, "изменение оценки")
        old = self.get(grade_id)
        year, semester, student_id, disc_id, grade = self._validate(data, grade_id)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE grades SET year = ?, semester = ?, student_id = ?, discipline_id = ?, "
                "grade = ? WHERE id = ?", (year, semester, student_id, disc_id, grade, grade_id))
            self.db.log_event(
                self.user.login, "grade_update",
                f"id={grade_id}; student_id={student_id}; discipline_id={disc_id}; "
                f"semester={semester}; grade: {old['grade']} -> {grade}")


class Services:
    def __init__(self, db, user):
        self.students = StudentService(db, user)
        self.curriculum = CurriculumService(db, user)
        self.grades = GradeService(db, user)
