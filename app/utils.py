"""Вспомогательные функции парсинга пользовательского ввода."""
from datetime import datetime


def parse_positive_float(text: str) -> float | None:
    """Парсит положительное число (поддерживает запятую). Иначе None."""
    try:
        value = float(text.replace(",", ".").replace(" ", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def parse_date(text: str) -> str | None:
    """Парсит дату ДД.ММ.ГГГГ и возвращает её в нормализованном виде, иначе None."""
    try:
        dt = datetime.strptime(text.strip(), "%d.%m.%Y")
    except ValueError:
        return None
    return dt.strftime("%d.%m.%Y")


def today_str() -> str:
    """Текущая дата в формате ДД.ММ.ГГГГ."""
    return datetime.now().strftime("%d.%m.%Y")
