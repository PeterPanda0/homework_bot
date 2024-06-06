class APIError(Exception):
    """Исключение для ошибок, связанных с доступом к API Практикума."""
    pass


class JSONDecodeError(Exception):
    """Исключение для ошибки преобразования ответа сервера в JSON формат."""
    pass
