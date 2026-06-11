"""Сгенерировать краткую PDF-инструкцию для сотрудников."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether,
)

FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
pdfmetrics.registerFont(TTFont("Body", FONT_PATH))

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontName="Body",
                   fontSize=18, leading=22, textColor=colors.HexColor("#1c3d5a"),
                   spaceAfter=4)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontName="Body",
                   fontSize=12, leading=15, textColor=colors.HexColor("#1c3d5a"),
                   spaceBefore=10, spaceAfter=4)
P = ParagraphStyle("P", parent=styles["Normal"], fontName="Body",
                  fontSize=10, leading=13)
Small = ParagraphStyle("Small", parent=styles["Normal"], fontName="Body",
                       fontSize=9, leading=11, textColor=colors.HexColor("#555555"))


def make_table(data, col_widths):
    """Таблица с зеброй, тонкими линиями и заголовком на синем."""
    t = Table(data, colWidths=col_widths, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Body", 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1c3d5a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f3f6fa")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#1c3d5a")),
    ]))
    return t


def cell(text, style=P):
    return Paragraph(text, style)


def build():
    doc = SimpleDocTemplate(
        "instruction.pdf", pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title="Бот доставок — инструкция",
    )
    story = []

    story.append(Paragraph("Бот доставок — краткая инструкция", H1))
    story.append(Paragraph("Чат «Доставки» в Битрикс24", Small))
    story.append(Spacer(1, 8))

    # 1. Создать заявку
    story.append(Paragraph("1. Создать заявку", H2))
    story.append(Paragraph(
        "Упомяните бота через <b>@Бот доставок</b> и напишите всё, что знаете "
        "о доставке. Прикрепите PDF — бот возьмёт номер и дату из имени файла. "
        "Поля не обязательны.", P))
    story.append(Spacer(1, 4))

    fields_table = make_table([
        [cell("Поле", P), cell("Пример", P)],
        [cell("Адрес", P),   cell("ул. Абая 5 / жетысу рынок / мкр Алгабас 2", P)],
        [cell("Клиент", P),  cell("Иванов И. / ТОО Алмаз", P)],
        [cell("Телефон", P), cell("+77001234567 / 8 700 123 45 67", P)],
        [cell("Время", P),   cell("сегодня / завтра", P)],
        [cell("Файл", P),    cell("Накладная … № 5203 от 11.06.2026.pdf", P)],
    ], col_widths=[28 * mm, 130 * mm])
    story.append(fields_table)
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "<b>Пример:</b> @Бот доставок Иванов И., жетысу рынок, +77001234567, завтра",
        Small))

    # 2. Ответы на сообщение бота
    story.append(Paragraph("2. Ответы на сообщение бота", H2))
    story.append(Paragraph(
        "Все действия — через <b>reply</b> (стрелка ↩️) на сообщение бота, "
        "не на сообщение менеджера.", P))
    story.append(Spacer(1, 4))

    actions = make_table([
        [cell("Ответ", P), cell("Действие", P)],
        [cell("<b>п</b>", P),       cell("📥 Принято в работу", P)],
        [cell("<b>д</b>", P),       cell("✅ Доставлено (авто-принимает, если не было «п»)", P)],
        [cell("<b>отмена</b>", P),  cell("❌ Отменить заявку", P)],
    ], col_widths=[25 * mm, 133 * mm])
    story.append(actions)
    story.append(Spacer(1, 3))
    story.append(Paragraph("Буквы — ровно одна: <b>п</b> или <b>д</b>, без слов вокруг.", Small))

    # 3. Редактирование
    story.append(Paragraph("3. Редактирование заявки", H2))
    story.append(Paragraph(
        "Reply на сообщение бота с метками — через запятую можно несколько полей "
        "сразу. Работает, пока заявка не закрыта.", P))
    story.append(Spacer(1, 4))

    edits = make_table([
        [cell("Что меняем", P), cell("Пример", P)],
        [cell("Адрес", P),    cell("Адрес: ул. Назарбаева 7", P)],
        [cell("Клиент", P),   cell("Клиент: Петров П.", P)],
        [cell("Телефон", P),  cell("Телефон: +77019998877", P)],
        [cell("Время", P),    cell("Время: завтра", P)],
    ], col_widths=[28 * mm, 130 * mm])
    story.append(edits)

    # 4. Отчёт и дайджесты
    story.append(Paragraph("4. Отчёт и автоматические дайджесты", H2))

    auto = make_table([
        [cell("Когда", P), cell("Что приходит", P)],
        [cell("по запросу", P),
         cell("Упомяните бота и напишите <b>отчет</b> — придёт сводка «сегодня + завтра».", P)],
        [cell("08:00", P),  cell("🌅 Доставки на сегодня (не принятые)", P)],
        [cell("17:30", P),  cell("🌙 Доставки на завтра", P)],
    ], col_widths=[28 * mm, 130 * mm])
    story.append(auto)

    # 5. Шпаргалка
    story.append(Paragraph("5. Шпаргалка", H2))
    cheat = make_table([
        [cell("Задача", P), cell("Как", P)],
        [cell("Создать заявку", P),
         cell("@Бот доставок <текст> + PDF", P)],
        [cell("Принять", P),       cell("reply на бота → <b>п</b>", P)],
        [cell("Доставлено", P),    cell("reply на бота → <b>д</b>", P)],
        [cell("Отменить", P),      cell("reply на бота → <b>отмена</b>", P)],
        [cell("Изменить поля", P), cell("reply на бота → Адрес: …, Клиент: …, Время: …", P)],
        [cell("Отчёт сейчас", P),  cell("@Бот доставок <b>отчет</b>", P)],
    ], col_widths=[36 * mm, 122 * mm])
    story.append(cheat)

    doc.build(story)
    print("OK: instruction.pdf")


if __name__ == "__main__":
    build()
