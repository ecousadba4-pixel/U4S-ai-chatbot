import textwrap

from app.utils.text import normalize_chat_text


def test_normalize_chat_text_removes_markdown_and_formats_lists():
    raw = (
        "Да, есть баня.\n"
        "**Условия:**\n"
        "* Баня работает круглый год\n"
        "* Аренда по часам\n"
    )

    result = normalize_chat_text(raw)

    assert result == (
        "Да, есть баня.\n"
        "Условия:\n"
        "— Баня работает круглый год\n"
        "— Аренда по часам"
    )


def test_normalize_chat_text_strips_headings_and_collapses_blank_lines():
    raw = textwrap.dedent(
        """
        # Заголовок

        - Первый пункт

        __Второй__ пункт
        ### Подзаголовок
        - Третий пункт
        """
    )

    result = normalize_chat_text(raw)

    assert result == (
        "Заголовок\n"
        "\n"
        "— Первый пункт\n"
        "\n"
        "Второй пункт\n"
        "Подзаголовок\n"
        "— Третий пункт"
    )
