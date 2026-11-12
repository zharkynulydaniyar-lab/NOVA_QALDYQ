"""Build the defence presentation (16:9, 12 slides) as PPTX.

    python tools/make_deck.py
    soffice --headless --convert-to pdf --outdir docs/presentation docs/presentation/Qaldyq-NOVA.pptx

Needs python-pptx. Screenshots come from tools/make_screens.js. Participant names are placeholders for the team to fill in.
Every economic and ecological figure on the slides is a scenario on stated assumptions, not a measured result."""
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "presentation"
IMG = OUT / "img"
DEEP, GREEN, LIME, INK, MUTED, PAPER = (RGBColor(0x0D, 0x3B, 0x2E), RGBColor(0x07, 0x5C, 0x46), RGBColor(0xD5, 0xF3, 0xA2), RGBColor(0x17, 0x30, 0x1F), RGBColor(0x5F, 0x73, 0x55), RGBColor(0xF4, 0xF8, 0xEE))

deck = Presentation()
deck.slide_width, deck.slide_height = Inches(13.333), Inches(7.5)
BLANK = deck.slide_layouts[6]


def box(slide, left, top, width, height, lines, size=18, color=INK, bold=False, gap=6):
    frame = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height)).text_frame
    frame.word_wrap = True
    for index, line in enumerate(lines if isinstance(lines, list) else [lines]):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        run = paragraph.add_run()
        run.text = line
        run.font.size, run.font.bold, run.font.color.rgb, run.font.name = Pt(size), bold, color, "Arial"
        paragraph.space_after = Pt(gap)
    return frame


def slide(number, kicker, title, dark=False):
    page = deck.slides.add_slide(BLANK)
    page.background.fill.solid()
    page.background.fill.fore_color.rgb = DEEP if dark else PAPER
    box(page, 0.7, 0.45, 9, 0.4, kicker.upper(), 12, LIME if dark else GREEN, True)
    box(page, 0.7, 0.85, 12, 1.2, title, 34 if not dark else 44, RGBColor(0xFF, 0xFF, 0xFF) if dark else DEEP, True)
    box(page, 11.9, 6.95, 1.2, 0.3, f"{number} / 12", 10, LIME if dark else MUTED)
    return page


def bullets(page, items, left=0.7, top=2.1, width=6.0, size=17):
    box(page, left, top, width, 4.6, ["•  " + item for item in items], size, INK, gap=11)


def picture(page, name, left, top, width=None, height=None):
    path = IMG / name
    if path.exists():
        page.shapes.add_picture(str(path), Inches(left), Inches(top), Inches(width) if width else None, Inches(height) if height else None)


def table(page, rows, left, top, width, height, size=13):
    shape = page.shapes.add_table(len(rows), len(rows[0]), Inches(left), Inches(top), Inches(width), Inches(height))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            cell = shape.table.cell(r, c)
            cell.text = str(value)
            for paragraph in cell.text_frame.paragraphs:
                for run in paragraph.runs:
                    run.font.size, run.font.bold, run.font.name = Pt(size), r == 0, "Arial"
                    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF) if r == 0 else INK
            cell.fill.solid()
            cell.fill.fore_color.rgb = GREEN if r == 0 else RGBColor(0xFF, 0xFF, 0xFF)


# 1. Title
page = slide(1, "ATU «Smart Food Industries» · Трек 1", "Qaldyq", dark=True)
box(page, 0.7, 2.3, 11.5, 1.4, "Цифровая система управления пищевыми отходами университетского комплекса", 26, RGBColor(0xFF, 0xFF, 0xFF))
box(page, 0.7, 4.3, 11.5, 1.2, ["Отходы → причина → рекомендация → действие → измеряемый результат"], 20, LIME, True)
box(page, 0.7, 5.6, 11.5, 1.2, ["Команда NOVA · Бірліктұзды Ермек · Валентинов Ерасыл · Жарқынұлы Данияр", "Кейс: АО «Алматинский технологический университет»"], 15, RGBColor(0xCF, 0xE3, 0xC9))

# 2. Problem and user
page = slide(2, "Проблема", "Пять таблиц, ноль общей картины")
bullets(page, ["Пять подразделений АТУ ведут учёт отходов в отдельных таблицах по единому образцу", "Сведение вручную: нет реестра, аналитики причин и данных для ESG-отчётности",
               "Мир, 2022 год: 1,05 млрд т пищевых отходов в рознице, общепите и домохозяйствах (UNEP Food Waste Index 2024)", "Объём по АТУ нам не предоставлен — его должна измерить система"], width=6.3)
table(page, [["Пользователь", "Что получает"], ["Сотрудник", "Запись за 4 действия с телефона"], ["Проверяющий", "Месячный отчёт: принять или вернуть"], ["Руководство", "Только принятые данные и сводки"],
             ["Студент", "Меню и бронь обеда"]], 7.3, 2.2, 5.3, 2.8)

# 3. Analogues
page = slide(3, "Анализ", "Аналоги и чем мы отличаемся")
table(page, [["Решение", "Что делает", "Ограничение для кейса АТУ"], ["Leanpath", "Взвешивание и аналитика отходов кухни", "Нужно оборудование; нет форм АТУ и проверки между организациями"],
             ["Winnow", "Распознавание отходов камерой и ИИ", "Нужно оборудование; интерфейс не на казахском"], ["Общая таблица", "Ручной ввод", "Нет ролей, статусов, истории и блокировки принятого"],
             ["Qaldyq", "Формы по таблицам АТУ, проверка, реестр, заказы, учёт, прогноз", "Ручной ввод веса; пилот ещё не проводился"]], 0.7, 2.2, 11.9, 3.4, 13)
box(page, 0.7, 5.9, 11.9, 0.9, "Мы не заявляем, что первые в мире. Цены и условия аналогов в Казахстане не запрашивались.", 14, MUTED)

# 4. Solution
page = slide(4, "Решение", "Одна цепочка вместо разрозненных таблиц")
table(page, [["Шаг", "Что происходит в системе"], ["Отходы", "Измерение: вид, кг или л, способ обращения, этап образования"], ["Причина", "Мнение сотрудника и статистическая связь — раздельно"],
             ["Рекомендация", "Прогноз спроса и предложение по объёму приготовления"], ["Действие", "Мероприятие утверждает руководство"], ["Выполнение", "Ответственный, срок, контрольный период"],
             ["Результат", "Показатели до и после; без заявлений о причинности"]], 0.7, 2.1, 11.9, 4.3, 14)

# 5. Working cycle
page = slide(5, "Работающий цикл", "От формы до квартального отчёта")
bullets(page, ["Формы по образцам АТУ для пяти организаций; новый вид добавляется из формы", "Отчёт за месяц: отправлен → на проверке → принят или возвращён с комментарием",
               "Принятые измерения блокируются и попадают в единый реестр", "Три графика, кг и л раздельно, квартальный XLSX и PDF", "83 серверных и 22 клиентских автоматических проверки пройдены"], width=5.4, size=15)
picture(page, "dashboard.png", 6.3, 2.1, width=6.6)

# 6. Student app
page = slide(6, "Студенты", "Меню и предзаказ на телефоне")
bullets(page, ["Меню доступно без входа; регистрация даёт только роль студента", "Лимит порций и интервалов; последняя порция достаётся одному покупателю",
               "Код и QR выдачи: заказ выдаётся один раз, продажа записывается один раз", "Онлайн-оплаты нет: бронь — это не оплата", "Без связи: сохранённое меню с временем, бронь недоступна",
               "Те же правила для сайта, Mini App и бота (бот — отдельный процесс)"], width=7.6, size=15)
picture(page, "student.png", 9.2, 1.9, height=5.2)

# 7. Technology
page = slide(7, "Технология", "Один сервер, одна база, проверяемые правила")
bullets(page, ["Python без внешних пакетов, SQLite, повторно запускаемые миграции", "Права проверяются на сервере в каждом запросе; студент закрыт от служебных данных",
               "Учёт столовой: закупки, партии со сроками годности, рецептуры, приготовление, продажи", "Деньги — целые тиыны; запасы — по средневзвешенной стоимости",
               "Закупка — не расход: в результат идёт стоимость использованных продуктов", "Офлайн-очередь отчётов; уведомления через очередь с повторами"], width=12, size=16)

# 8. ML
page = slide(8, "Прогноз спроса", "ML не считается лучшим заранее")
bullets(page, ["Прогнозируем общий спрос: столовая × блюдо × дата", "Предзаказы — нижняя граница, а не прибавка", "Три метода сравниваются на последних неделях истории",
               "Признаки — только из прошлого; дни с нехваткой блюда исключены из ошибки", "Модель обучена на синтетической демо-истории — это не результат эксплуатации", "План утверждает сотрудник"], width=5.3, size=15)
picture(page, "forecast.png", 6.2, 2.1, width=6.7)

# 9. Actions
page = slide(9, "Мероприятия", "От проблемы к измеренному результату")
bullets(page, ["Предложено → утверждено → выполняется → оценивается → завершено", "Базовый и контрольный периоды: кг/100 порций, остатки, нехватка",
               "Система называет, что мешает сравнению: меню, посещаемость, дни недели", "Отходов меньше, но нехваток больше — предложение пересмотреть действие",
               "Расчётная экономия отдельно от подтверждённой документом"], width=5.3, size=15)
picture(page, "action.png", 6.2, 2.1, width=6.7)

# 10. Economics and ecology
page = slide(10, "Экономика и экология", "Сценарии на открытых допущениях")
table(page, [["Сценарий", "Сокращение", "Чистая экономия / мес", "Окупаемость"], ["Осторожный", "5%", "30 000 ₸", "11,7 мес."], ["Базовый", "15%", "150 000 ₸", "2,3 мес."], ["Высокий", "25%", "270 000 ₸", "1,3 мес."]],
      0.7, 2.1, 7.0, 2.2, 14)
box(page, 0.7, 4.5, 7.0, 2.4, ["База: 1 000 кг/мес × 1 200 ₸/кг; CAPEX 350 000 ₸; OPEX 30 000 ₸/мес", "Трудозатраты: около 20 часов в месяц при 300 записях (сценарий)",
                               "Это расчёты, а не результаты: пилот не проводился"], 14, MUTED, gap=8)
box(page, 8.2, 2.1, 4.6, 4.6, ["Экология (базовый сценарий)", "1,8 т отходов в год", "4,5 т CO₂-экв. в год при условном коэффициенте 2,5 кг/кг", "Источник коэффициента не подтверждён",
                               "Переработка: четыре раздельных показателя", "ЦУР 12.3: кг на 100 порций"], 15, INK, gap=9)

# 11. Pilot
page = slide(11, "Внедрение", "Пилот → все организации АТУ → другие вузы")
table(page, [["Этап", "Срок", "Что делаем"], ["Пилот: столовый комплекс", "6 недель", "База 2 недели, мероприятие 2 недели, сравнение"], ["Все пять организаций АТУ", "2 месяца", "Справочники и аккаунты через интерфейс, без изменения кода"],
             ["Другие вузы", "после пилота", "Отдельная база и формы; спрос и тариф не исследованы"]], 0.7, 2.1, 11.9, 2.3, 14)
bullets(page, ["Риски: неточные веса, нагрузка на сотрудников, сезонность, персональные данные, готовность вузов платить",
               "Ответ: порядок взвешивания, быстрый ввод, нормирование на порции, только служебные данные"], top=4.7, width=11.9, size=15)

# 12. Team and ask
page = slide(12, "Команда и запрос", "Что нам нужно для пилота", dark=True)
box(page, 0.7, 2.3, 6.0, 3.6, ["Команда NOVA:", "Бірліктұзды Ермек", "Валентинов Ерасыл", "Жарқынұлы Данияр", "Направления: проблема и интерфейс · сервер и данные · прогноз, экономика, внедрение"],
    17, RGBColor(0xFF, 0xFF, 0xFF), gap=12)
box(page, 7.0, 2.3, 5.8, 3.6, ["Запрос:", "одна столовая на 6 недель", "ответственный сотрудник и проверяющий", "доступ к действующим таблицам", "весы и телефон"], 17, LIME, gap=10)
box(page, 0.7, 6.1, 12, 0.8, "Декларация: основа прототипа подготовлена до хакатона; код, тексты и иллюстрации созданы с помощью генеративного ИИ. Все данные в демо — синтетические.", 12,
    RGBColor(0xCF, 0xE3, 0xC9))

OUT.mkdir(parents=True, exist_ok=True)
deck.save(OUT / "Qaldyq-NOVA.pptx")
print("slides:", len(deck.slides), "→", OUT / "Qaldyq-NOVA.pptx")
