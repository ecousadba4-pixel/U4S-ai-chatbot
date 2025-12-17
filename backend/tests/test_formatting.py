import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.booking.entities import BookingEntities
from app.booking.models import BookingQuote, Guests
from app.chat.formatting import format_shelter_quote
from app.core.config import get_settings


def _reset_settings_cache():
    try:
        get_settings.cache_clear()
    except AttributeError:
        pass


def _prepare_settings_env(monkeypatch, max_options: str) -> None:
    monkeypatch.setenv("MAX_OPTIONS", max_options)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("AMVERA_API_TOKEN", "test-amvera")
    monkeypatch.setenv("SHELTER_CLOUD_TOKEN", "test-shelter")
    _reset_settings_cache()


def test_format_shelter_quote_renders_readable_blocks(monkeypatch):
    _prepare_settings_env(monkeypatch, "6")

    entities = BookingEntities(
        checkin="2025-01-20",
        checkout="2025-01-22",
        adults=2,
        children=1,
        nights=2,
        room_type=None,
        missing_fields=[],
    )
    guests = Guests(adults=2, children=1)
    offers = [
        BookingQuote(
            room_name="Стандарт",
            total_price=25000,
            currency="RUB",
            breakfast_included=False,
            room_area=30,
            check_in=entities.checkin or "",
            check_out=entities.checkout or "",
            guests=guests,
        ),
        BookingQuote(
            room_name="Эконом",
            total_price=19230,
            currency="RUB",
            breakfast_included=True,
            room_area=None,
            check_in=entities.checkin or "",
            check_out=entities.checkout or "",
            guests=guests,
        ),
    ]

    answer = format_shelter_quote(entities, offers)

    assert (
        answer
        == "На даты 20.01–22.01 (2 ночи) для 2 взрослых и 1 детей доступны варианты:\n\n"
        "🏠 Эконом\n"
        "— 19 230 ₽ (завтрак включён)\n\n"
        "🏠 Стандарт (30 м²)\n"
        "— 25 000 ₽"
    )

    _reset_settings_cache()


def test_format_shelter_quote_respects_limit_and_currency(monkeypatch):
    _prepare_settings_env(monkeypatch, "6")  # MAX_OPTIONS больше не используется, лимит всегда 3

    entities = BookingEntities(
        checkin="2025-03-01",
        checkout="2025-03-04",
        adults=1,
        children=0,
        nights=None,
        room_type=None,
        missing_fields=[],
    )
    guests = Guests(adults=1, children=0)
    offers = [
        BookingQuote(
            room_name="Дорм",
            total_price=4500,
            currency="EUR",
            breakfast_included=None,  # type: ignore[arg-type]
            room_area=None,
            check_in=entities.checkin or "",
            check_out=entities.checkout or "",
            guests=guests,
        ),
        BookingQuote(
            room_name="Стандарт",
            total_price=5000,
            currency="USD",
            breakfast_included=None,  # type: ignore[arg-type]
            room_area=None,
            check_in=entities.checkin or "",
            check_out=entities.checkout or "",
            guests=guests,
        ),
        BookingQuote(
            room_name="Люкс",
            total_price=4700,
            currency="RUB",
            breakfast_included=False,
            room_area=40,
            check_in=entities.checkin or "",
            check_out=entities.checkout or "",
            guests=guests,
        ),
    ]

    answer = format_shelter_quote(entities, offers)

    # С новым лимитом 3 варианта - все 3 показываются
    assert (
        answer
        == "На даты 01.03–04.03 (3 ночи) для 1 взрослых доступны варианты:\n\n"
        "🏠 Дорм\n"
        "— 4 500 EUR\n\n"
        "🏠 Люкс (40 м²)\n"
        "— 4 700 ₽\n\n"
        "🏠 Стандарт\n"
        "— 5 000 USD"
    )

    _reset_settings_cache()


def test_format_shelter_quote_deduplicates_room_types(monkeypatch):
    _prepare_settings_env(monkeypatch, "5")

    entities = BookingEntities(
        checkin="2024-12-19",
        checkout="2024-12-21",
        adults=2,
        children=2,
        nights=2,
        room_type=None,
        missing_fields=[],
    )
    guests = Guests(adults=2, children=2)
    offers = [
        BookingQuote(
            room_name="Студия",
            total_price=28738,
            currency="RUB",
            breakfast_included=True,
            room_area=24,
            check_in=entities.checkin or "",
            check_out=entities.checkout or "",
            guests=guests,
        ),
        BookingQuote(
            room_name="Студия",
            total_price=30250,
            currency="RUB",
            breakfast_included=True,
            room_area=24,
            check_in=entities.checkin or "",
            check_out=entities.checkout or "",
            guests=guests,
        ),
    ]

    answer = format_shelter_quote(entities, offers)

    assert "28 738 ₽" in answer
    assert "30 250 ₽" not in answer
    # Новый формат: площадь в скобках после названия, завтрак в скобках после цены
    assert "🏠 Студия (24 м²)" in answer
    assert "(завтрак включён)" in answer

    _reset_settings_cache()


def test_format_shelter_quote_keeps_min_price_per_type(monkeypatch):
    _prepare_settings_env(monkeypatch, "6")

    entities = BookingEntities(
        checkin="2024-12-19",
        checkout="2024-12-21",
        adults=2,
        children=0,
        nights=2,
        room_type=None,
        missing_fields=[],
    )
    guests = Guests(adults=2, children=0)
    offers = [
        BookingQuote(
            room_name="Шале",
            total_price=26160,
            currency="RUB",
            breakfast_included=True,
            room_area=34,
            check_in=entities.checkin or "",
            check_out=entities.checkout or "",
            guests=guests,
        ),
        BookingQuote(
            room_name="Шале",
            total_price=28123,
            currency="RUB",
            breakfast_included=True,
            room_area=34,
            check_in=entities.checkin or "",
            check_out=entities.checkout or "",
            guests=guests,
        ),
        BookingQuote(
            room_name="Семейный",
            total_price=32927,
            currency="RUB",
            breakfast_included=True,
            room_area=48,
            check_in=entities.checkin or "",
            check_out=entities.checkout or "",
            guests=guests,
        ),
    ]

    answer = format_shelter_quote(entities, offers)

    assert answer.index("26 160") < answer.index("32 927")
    assert "28 123" not in answer
    assert "Шале" in answer and "Семейный" in answer

    _reset_settings_cache()


def test_format_shelter_quote_shows_only_3_and_remaining(monkeypatch):
    """Проверяет, что показываются только 3 варианта и есть сообщение о дополнительных."""
    _prepare_settings_env(monkeypatch, "6")

    entities = BookingEntities(
        checkin="2024-12-19",
        checkout="2024-12-21",
        adults=2,
        children=1,
        nights=2,
        room_type=None,
        missing_fields=[],
    )
    guests = Guests(adults=2, children=1)
    offers = [
        BookingQuote(
            room_name="Студия",
            total_price=18611,
            currency="RUB",
            breakfast_included=True,
            room_area=24,
            check_in=entities.checkin or "",
            check_out=entities.checkout or "",
            guests=guests,
        ),
        BookingQuote(
            room_name="Шале Комфорт",
            total_price=26290,
            currency="RUB",
            breakfast_included=True,
            room_area=42,
            check_in=entities.checkin or "",
            check_out=entities.checkout or "",
            guests=guests,
        ),
        BookingQuote(
            room_name="Семейный",
            total_price=29583,
            currency="RUB",
            breakfast_included=True,
            room_area=48,
            check_in=entities.checkin or "",
            check_out=entities.checkout or "",
            guests=guests,
        ),
        BookingQuote(
            room_name="Люкс",
            total_price=35000,
            currency="RUB",
            breakfast_included=True,
            room_area=60,
            check_in=entities.checkin or "",
            check_out=entities.checkout or "",
            guests=guests,
        ),
        BookingQuote(
            room_name="Президентский",
            total_price=50000,
            currency="RUB",
            breakfast_included=True,
            room_area=80,
            check_in=entities.checkin or "",
            check_out=entities.checkout or "",
            guests=guests,
        ),
    ]

    answer = format_shelter_quote(entities, offers)

    # Проверяем новый формат
    assert "🏠 Студия (24 м²)" in answer
    assert "— 18 611 ₽ (завтрак включён)" in answer
    assert "🏠 Шале Комфорт (42 м²)" in answer
    assert "🏠 Семейный (48 м²)" in answer
    
    # Проверяем что показаны только 3 варианта
    assert "Люкс" not in answer
    assert "Президентский" not in answer
    
    # Проверяем сообщение о дополнительных вариантах
    assert "Ещё доступно 2 вариантов. Показать все?" in answer

    _reset_settings_cache()
