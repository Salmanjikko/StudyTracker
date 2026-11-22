"""Исключения приложения (ST001–ST008).

Все они наследуются от AppError. Общий обработчик (hooks.ErrorHandler)
откатывает транзакцию, показывает сообщение и пишет событие в журнал.
"""


class AppError(Exception):
    """Общий класс ошибки приложения."""

    code = "ST000"
    default_message = "Внутренняя ошибка программы. Данные не изменены."

    def __init__(self, message=None, field=None, actor=None):
        self.message = message or self.default_message
        self.field = field    # поле формы, которое нужно подсветить
        self.actor = actor    # логин, если пользователь ещё не вошёл
        super().__init__(self.message)


class GradeOutOfRangeError(AppError):
    code = "ST001"
    default_message = "Недопустимое значение оценки."


class DuplicateGradeError(AppError):
    code = "ST002"
    default_message = ("Оценка по этой дисциплине и семестру у студента уже есть. "
                       "Измените существующую запись.")


class NotFoundError(AppError):
    code = "ST003"
    default_message = "Данные не найдены"


class InvalidInputError(AppError):
    code = "ST004"
    default_message = "Неверно заполнено поле."


class NotInCurriculumError(AppError):
    code = "ST005"
    default_message = "Дисциплины нет в учебном плане специальности студента."


class AccessDeniedError(AppError):
    code = "ST006"
    default_message = "Действие недоступно для вашей роли."


class LoginError(AppError):
    code = "ST007"
    default_message = "Неверный логин или пароль."


class DatabaseUnavailableError(AppError):
    code = "ST008"
    default_message = "База данных недоступна."
