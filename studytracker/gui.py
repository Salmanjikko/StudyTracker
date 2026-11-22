"""Графический интерфейс: окно входа, вкладки и формы."""
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from .auth import AuthService
from .db import REPORT_FORMS, ROLE_DEAN, ROLE_LABELS, ROLE_TEACHER, STUDY_FORMS
from .hooks import ErrorHandler
from .services import Services

ERROR_BG = "#ffd6d6"


class App:
    """Хранит базу, текущего пользователя и обработчик ошибок."""

    def __init__(self, root, db):
        self.root = root
        self.db = db
        self.user = None
        self.services = None
        self.handler = ErrorHandler(db, lambda: self.user)
        self.auth = AuthService(db)
        ttk.Style().configure("Err.TCombobox", fieldbackground=ERROR_BG)
        self.show_login()

    def report(self, exc, parent=None):
        """Передаёт ошибку обработчику и показывает сообщение."""
        err = self.handler.handle(exc)
        title = "Ошибка" if err.code == "ST000" else f"Ошибка {err.code}"
        messagebox.showerror(title, err.message, parent=parent or self.root)
        return err

    def safe(self, parent, fn, *args):
        try:
            return True, fn(*args)
        except Exception as exc:  # ошибка не должна закрывать программу
            self.report(exc, parent)
            return False, None

    def _clear(self):
        for child in self.root.winfo_children():
            child.destroy()

    def show_login(self):
        self._clear()
        self.user = None
        self.root.title("StudyTracker — вход")
        self.root.geometry("360x230")
        self.root.minsize(360, 230)
        LoginFrame(self.root, self).pack(expand=True)

    def do_login(self, login, password):
        user = self.auth.login(login, password)
        self.user = user
        self.services = Services(self.db, user)
        self.show_main()

    def show_main(self):
        self._clear()
        self.root.title(f"StudyTracker — {ROLE_LABELS[self.user.role]}: {self.user.login}")
        self.root.geometry("1050x620")
        self.root.minsize(900, 520)
        MainFrame(self.root, self).pack(fill="both", expand=True)


class LoginFrame(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=20)
        self.app = app
        ttk.Label(self, text="StudyTracker", font=("TkDefaultFont", 16, "bold")).grid(
            row=0, column=0, columnspan=2, pady=(0, 12))
        ttk.Label(self, text="Логин").grid(row=1, column=0, sticky="w", pady=4)
        self.login_var = tk.StringVar()
        self.login_entry = ttk.Entry(self, textvariable=self.login_var, width=24)
        self.login_entry.grid(row=1, column=1, pady=4)
        ttk.Label(self, text="Пароль").grid(row=2, column=0, sticky="w", pady=4)
        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(
            self, textvariable=self.password_var, show="•", width=24)
        self.password_entry.grid(row=2, column=1, pady=4)
        ttk.Button(self, text="Войти", command=self.submit).grid(
            row=3, column=0, columnspan=2, pady=(12, 0))
        self.login_entry.focus_set()
        master.bind("<Return>", lambda _e: self.submit())

    def submit(self):
        try:
            self.master.unbind("<Return>")
            self.app.do_login(self.login_var.get(), self.password_var.get())
        except Exception as exc:
            self.master.bind("<Return>", lambda _e: self.submit())
            self.app.report(exc, self.master)
            self.password_var.set("")
            self.password_entry.focus_set()


class FormDialog(tk.Toplevel):
    """Форма добавления и изменения.

    fields: список словарей с ключами key, label, type (entry, choice или combo) и choices.
    """

    def __init__(self, parent, app, title, fields, initial, submit_text, on_submit):
        super().__init__(parent)
        self.app = app
        self.on_submit = on_submit
        self.fields = fields
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.vars, self.widgets, self.defaults = {}, {}, {}
        body = ttk.Frame(self, padding=12)
        body.pack()
        for row, f in enumerate(fields):
            ttk.Label(body, text=f["label"]).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 10))
            value = initial.get(f["key"], "")
            if f["type"] == "entry":
                var = tk.StringVar(value="" if value is None else str(value))
                widget = tk.Entry(body, textvariable=var, width=38)
                self.defaults[f["key"]] = widget.cget("bg")
            else:
                if f["type"] == "choice":
                    value = next((lbl for lbl, val in f["choices"] if val == value), "")
                var = tk.StringVar(value=value)
                widget = ttk.Combobox(
                    body, textvariable=var, values=[lbl for lbl, _ in f["choices"]], width=36,
                    state="readonly" if f["type"] == "choice" else "normal")
            widget.grid(row=row, column=1, pady=3)
            self.vars[f["key"]], self.widgets[f["key"]] = var, widget
        buttons = ttk.Frame(body)
        buttons.grid(row=len(fields), column=0, columnspan=2, pady=(12, 0))
        ttk.Button(buttons, text=submit_text, command=self.submit).pack(side="left", padx=4)
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="left", padx=4)
        self.bind("<Return>", lambda _e: self.submit())
        self.bind("<Escape>", lambda _e: self.destroy())
        first = self.widgets[fields[0]["key"]]
        first.focus_set()
        self.grab_set()

    def _mark(self, key, bad):
        widget = self.widgets[key]
        if isinstance(widget, ttk.Combobox):
            widget.configure(style="Err.TCombobox" if bad else "TCombobox")
        else:
            widget.configure(bg=ERROR_BG if bad else self.defaults[key])

    def collect(self):
        values = {}
        for f in self.fields:
            text = self.vars[f["key"]].get()
            if f["type"] == "choice":
                values[f["key"]] = dict(f["choices"]).get(text)
            else:
                values[f["key"]] = text
        return values

    def submit(self):
        for key in self.widgets:
            self._mark(key, False)
        try:
            self.on_submit(self.collect())
        except Exception as exc:
            err = self.app.report(exc, self)
            if err.field in self.widgets:
                self._mark(err.field, True)
                self.widgets[err.field].focus_set()
            return
        self.destroy()


class DataTab(ttk.Frame):
    """Вкладка с таблицей и кнопками «Добавить» и «Изменить»."""

    columns = ()
    editable_role = None

    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app
        self.can_edit = app.user.role == self.editable_role
        self.build_top()
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, pady=6)
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in self.columns],
                                 show="headings", selectmode="browse")
        for key, title, width in self.columns:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        add_btn = ttk.Button(bar, text="Добавить", command=self.on_add)
        edit_btn = ttk.Button(bar, text="Изменить", command=self.on_edit)
        add_btn.pack(side="left", padx=(0, 6))
        edit_btn.pack(side="left")
        if self.can_edit:
            self.tree.bind("<Double-1>", lambda _e: self.on_edit())
        else:
            add_btn.state(["disabled"])
            edit_btn.state(["disabled"])
            ttk.Label(bar, text="Для вашей роли раздел доступен только для просмотра").pack(
                side="left", padx=12)
        self.refresh()

    def build_top(self):
        pass

    def fetch(self):
        raise NotImplementedError

    def open_form(self, item_id):
        raise NotImplementedError

    def refresh(self):
        ok, rows = self.app.safe(self, self.fetch)
        if not ok:
            return
        self.tree.delete(*self.tree.get_children())
        for iid, values in rows:
            self.tree.insert("", "end", iid=str(iid), values=values)

    def on_add(self):
        self.open_form(None)

    def on_edit(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Изменение", "Сначала выберите запись в таблице.", parent=self)
            return
        self.open_form(int(selection[0]))


class StudentsTab(DataTab):
    columns = (("last_name", "Фамилия", 160), ("first_name", "Имя", 130),
               ("middle_name", "Отчество", 160), ("group", "Группа", 90),
               ("year", "Год поступления", 120), ("form", "Форма обучения", 130))
    editable_role = ROLE_DEAN
    ALL_GROUPS = "Все группы"

    def build_top(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Label(bar, text="Фамилия:").pack(side="left")
        self.name_var = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.name_var, width=22)
        entry.pack(side="left", padx=(4, 12))
        entry.bind("<Return>", lambda _e: self.refresh())
        ttk.Label(bar, text="Группа:").pack(side="left")
        ok, groups = self.app.safe(self, self.app.services.students.groups)
        self.group_ids = {g["name"]: g["id"] for g in groups} if ok else {}
        self.group_var = tk.StringVar(value=self.ALL_GROUPS)
        ttk.Combobox(bar, textvariable=self.group_var, state="readonly", width=14,
                     values=[self.ALL_GROUPS] + list(self.group_ids)).pack(side="left", padx=4)
        ttk.Button(bar, text="Найти", command=self.refresh).pack(side="left", padx=4)
        ttk.Button(bar, text="Сбросить", command=self.reset).pack(side="left")

    def reset(self):
        self.name_var.set("")
        self.group_var.set(self.ALL_GROUPS)
        self.refresh()

    def fetch(self):
        rows = self.app.services.students.list(
            self.name_var.get(), self.group_ids.get(self.group_var.get()))
        return [(r["id"], (r["last_name"], r["first_name"], r["middle_name"], r["group_name"],
                           r["admission_year"], r["study_form"])) for r in rows]

    def open_form(self, item_id):
        svc = self.app.services.students
        initial = {}
        if item_id is not None:
            ok, row = self.app.safe(self, svc.get, item_id)
            if not ok:
                return
            initial = dict(row)
        ok, groups = self.app.safe(self, svc.groups)
        if not ok:
            return
        fields = [
            {"key": "last_name", "label": "Фамилия", "type": "entry"},
            {"key": "first_name", "label": "Имя", "type": "entry"},
            {"key": "middle_name", "label": "Отчество", "type": "entry"},
            {"key": "group_id", "label": "Группа", "type": "choice",
             "choices": [(g["name"], g["id"]) for g in groups]},
            {"key": "admission_year", "label": "Год поступления", "type": "entry"},
            {"key": "study_form", "label": "Форма обучения", "type": "choice",
             "choices": [(f, f) for f in STUDY_FORMS]},
        ]

        def submit(values):
            if item_id is None:
                svc.add(values)
            else:
                svc.update(item_id, values)
            self.refresh()

        FormDialog(self, self.app, "Студент", fields, initial,
                   "Добавить" if item_id is None else "Сохранить", submit)


class CurriculumTab(DataTab):
    columns = (("specialty", "Специальность", 300), ("discipline", "Дисциплина", 260),
               ("semester", "Семестр", 80), ("hours", "Часы", 80),
               ("report_form", "Форма отчётности", 140))
    editable_role = ROLE_DEAN

    def fetch(self):
        rows = self.app.services.curriculum.list()
        return [(r["id"], (r["specialty"], r["discipline"], r["semester"], r["hours"],
                           r["report_form"])) for r in rows]

    def open_form(self, item_id):
        svc = self.app.services.curriculum
        initial = {}
        if item_id is not None:
            ok, row = self.app.safe(self, svc.get, item_id)
            if not ok:
                return
            initial = dict(row)
        ok, specialties = self.app.safe(self, svc.specialties)
        ok2, disciplines = self.app.safe(self, svc.disciplines)
        if not (ok and ok2):
            return
        names = [d["name"] for d in disciplines]
        fields = [
            {"key": "specialty_id", "label": "Специальность", "type": "choice",
             "choices": [(s["name"], s["id"]) for s in specialties]},
            {"key": "discipline", "label": "Дисциплина", "type": "combo",
             "choices": [(n, n) for n in names]},
            {"key": "semester", "label": "Семестр (1–12)", "type": "entry"},
            {"key": "hours", "label": "Количество часов", "type": "entry"},
            {"key": "report_form", "label": "Форма отчётности", "type": "choice",
             "choices": [(f, f) for f in REPORT_FORMS]},
        ]

        def submit(values):
            if item_id is None:
                svc.add(values)
            else:
                svc.update(item_id, values)
            self.refresh()

        FormDialog(self, self.app, "Строка учебного плана", fields, initial,
                   "Добавить" if item_id is None else "Сохранить", submit)


class GradesTab(DataTab):
    columns = (("year", "Год", 70), ("semester", "Семестр", 80), ("student", "Студент", 260),
               ("group", "Группа", 90), ("discipline", "Дисциплина", 240),
               ("grade", "Оценка", 90))
    editable_role = ROLE_TEACHER

    def fetch(self):
        rows = self.app.services.grades.list()
        return [(r["id"], (r["year"], r["semester"], r["student"].strip(), r["group_name"],
                           r["discipline"], r["grade"])) for r in rows]

    def open_form(self, item_id):
        svc = self.app.services.grades
        initial = {}
        if item_id is not None:
            ok, row = self.app.safe(self, svc.get, item_id)
            if not ok:
                return
            initial = dict(row)
        else:
            today = date.today()
            initial = {"year": today.year if today.month >= 9 else today.year - 1}
        ok, students = self.app.safe(self, self.app.services.students.list)
        ok2, disciplines = self.app.safe(self, self.app.services.curriculum.disciplines)
        if not (ok and ok2):
            return
        fields = [
            {"key": "year", "label": "Год (начало учебного года)", "type": "entry"},
            {"key": "semester", "label": "Семестр (1–12)", "type": "entry"},
            {"key": "student_id", "label": "Студент", "type": "choice",
             "choices": [(f"{s['last_name']} {s['first_name']} {s['middle_name']} "
                          f"({s['group_name']})".replace("  ", " "), s["id"])
                         for s in students]},
            {"key": "discipline_id", "label": "Дисциплина", "type": "choice",
             "choices": [(d["name"], d["id"]) for d in disciplines]},
            {"key": "grade", "label": "Оценка (2–5, зачёт, незачёт)", "type": "combo",
             "choices": [(g, g) for g in ("2", "3", "4", "5", "зачёт", "незачёт")]},
        ]

        def submit(values):
            if item_id is None:
                svc.add(values)
            else:
                svc.update(item_id, values)
            self.refresh()

        FormDialog(self, self.app, "Оценка", fields, initial,
                   "Добавить" if item_id is None else "Сохранить", submit)


class SummaryTab(ttk.Frame):
    """Подсчёт студентов по форме обучения и данные по дисциплине."""

    def __init__(self, master, app):
        super().__init__(master, padding=12)
        self.app = app

        box1 = ttk.LabelFrame(self, text="Студенты по форме обучения", padding=10)
        box1.pack(fill="x", pady=(0, 12))
        ttk.Label(box1, text="Форма обучения:").pack(side="left")
        self.form_var = tk.StringVar()
        combo = ttk.Combobox(box1, textvariable=self.form_var, values=list(STUDY_FORMS),
                             state="readonly", width=14)
        combo.pack(side="left", padx=6)
        combo.bind("<<ComboboxSelected>>", lambda _e: self.show_count())
        ttk.Button(box1, text="Показать", command=self.show_count).pack(side="left")
        self.count_label = ttk.Label(box1, text="", font=("TkDefaultFont", 11, "bold"))
        self.count_label.pack(side="left", padx=16)

        box2 = ttk.LabelFrame(self, text="Данные по дисциплине", padding=10)
        box2.pack(fill="both", expand=True)
        top = ttk.Frame(box2)
        top.pack(fill="x")
        ttk.Label(top, text="Дисциплина:").pack(side="left")
        self.disc_var = tk.StringVar()
        self.disc_ids = {}
        self.disc_combo = ttk.Combobox(top, textvariable=self.disc_var, state="readonly", width=40)
        self.disc_combo.pack(side="left", padx=6)
        self.disc_combo.bind("<<ComboboxSelected>>", lambda _e: self.show_discipline())
        ttk.Button(top, text="Показать", command=self.show_discipline).pack(side="left")
        cols = (("specialty", "Специальность", 330), ("semester", "Семестр", 80),
                ("hours", "Часы", 80), ("report_form", "Форма отчётности", 150))
        self.tree = ttk.Treeview(box2, columns=[c[0] for c in cols], show="headings", height=6)
        for key, title, width in cols:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(8, 0))
        self.refresh()

    def refresh(self):
        ok, rows = self.app.safe(self, self.app.services.curriculum.disciplines)
        if ok:
            self.disc_ids = {r["name"]: r["id"] for r in rows}
            self.disc_combo.configure(values=list(self.disc_ids))

    def show_count(self):
        if not self.form_var.get():
            messagebox.showinfo("Подсчёт", "Выберите форму обучения.", parent=self)
            return
        ok, n = self.app.safe(self, self.app.services.students.count_by_form,
                              self.form_var.get())
        if ok:
            self.count_label.configure(
                text=f"Студентов на форме «{self.form_var.get()}»: {n}")

    def show_discipline(self):
        if not self.disc_var.get():
            messagebox.showinfo("Дисциплина", "Выберите дисциплину.", parent=self)
            return
        self.tree.delete(*self.tree.get_children())
        ok, rows = self.app.safe(self, self.app.services.curriculum.discipline_info,
                                 self.disc_ids.get(self.disc_var.get()))
        if ok:
            for r in rows:
                self.tree.insert("", "end", values=(r["specialty"], r["semester"],
                                                    r["hours"], r["report_form"]))


class MainFrame(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=6, pady=6)
        self.tabs = [
            (StudentsTab(notebook, app), "Студенты"),
            (CurriculumTab(notebook, app), "Учебный план"),
            (GradesTab(notebook, app), "Журнал успеваемости"),
            (SummaryTab(notebook, app), "Сводка"),
        ]
        for tab, title in self.tabs:
            notebook.add(tab, text=title)
        # данные могли измениться на другой вкладке, поэтому обновляем при переключении
        notebook.bind("<<NotebookTabChanged>>", lambda _e: self._on_tab(notebook))

    def _on_tab(self, notebook):
        tab = self.nametowidget(notebook.select())
        if hasattr(tab, "refresh"):
            tab.refresh()
