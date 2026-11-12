"""Modern defence deck for Qaldyq, Russian and Kazakh (16:9, 12 slides, PPTX).

    python tools/make_deck_v2.py            # both languages
    python tools/make_deck_v2.py ru         # one language
    soffice --headless --convert-to pdf --outdir docs/presentation docs/presentation/Qaldyq-NOVA-ru.pptx

Charts are native PowerPoint charts filled from the demo database (data/qaldyq-v5.4.sqlite3) when it exists.
Screenshots come from tools/make_screens.js (img/ for Russian, img-kk/ for Kazakh).
All economic and ecological figures are scenarios on stated assumptions, not measured results."""
import json
import sqlite3
import sys
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "presentation"
DB = ROOT / "data" / "qaldyq-v5.4.sqlite3"
FONT = "Inter"

INK, DEEP, FOREST, GREEN, LEAF, LIME, MINT = "0B1F17", "0D3B2E", "0F4A39", "075C46", "5FA36B", "D5F3A2", "EAF4DE"
PAPER, CARD, LINE, MUTED, AMBER, CORAL, WHITE = "F6F9F1", "FFFFFF", "DCE7D2", "5E7255", "E7A33C", "D9644A", "FFFFFF"
TEAM = ["Бірліктұзды Ермек", "Валентинов Ерасыл", "Жарқынұлы Данияр"]


def rgb(value):
    return RGBColor.from_string(value)


# ---------------------------------------------------------------- data

def load_data():
    data = {"methods": {"existing": 4.41, "weekday": 4.45, "ml": 3.53},
            "orgs": [("Асхана", 1512), ("ATU INN", 1072), ("Кофехана", 537), ("ТПП", 150), ("ТХиПП", 132)],
            "types": [("Картон ыдыс", "Картонная тара", 676), ("Залдан шыққан тамақ қалдығы", "Пищевые отходы из зала", 534),
                      ("Көкөніс тазалағы", "Очистки овощей", 526), ("Ет өнімдерінің кесінділері", "Обрезки мясопродуктов", 521),
                      ("Сатылмаған өнім қалдығы", "Остатки нереализованной продукции", 507)]}
    if DB.exists():
        db = sqlite3.connect(DB)
        row = db.execute("SELECT report FROM forecast_models WHERE active=1").fetchone()
        if row:
            data["methods"] = {k: v["mae"] for k, v in json.loads(row[0])["methods"].items() if v}
        accepted = "FROM items i JOIN reports r ON r.id=i.report_id JOIN categories c ON c.id=i.category_id WHERE r.status='accepted' AND c.unit='kg'"
        data["orgs"] = [(s, round(v)) for s, v in db.execute(f"SELECT o.short,SUM(i.kg) {accepted.replace('WHERE', 'JOIN organizations o ON o.id=r.org_id WHERE')} GROUP BY o.id ORDER BY o.id")]
        data["types"] = [(a, b or a, round(v)) for a, b, v in db.execute(f"SELECT c.name,c.name_ru,SUM(i.kg) s {accepted} GROUP BY c.id ORDER BY s DESC LIMIT 5")]
    return data


# ---------------------------------------------------------------- text

T = {
    "track": ("ATU «Smart Food Industries» · Трек 1", "ATU «Smart Food Industries» · 1-трек"),
    "subtitle": ("Цифровая система управления пищевыми отходами университетского комплекса", "Университет кешеніндегі тамақ қалдықтарын басқарудың цифрлық жүйесі"),
    "chain": (["Отходы", "Причина", "Рекомендация", "Действие", "Результат"], ["Қалдық", "Себеп", "Ұсыныс", "Әрекет", "Нәтиже"]),
    "team": ("Команда NOVA", "NOVA командасы"),
    "case": ("Кейс: АО «Алматинский технологический университет»", "Кейс: «Алматы технологиялық университеті» АҚ"),
    "p_k": ("Проблема", "Мәселе"), "p_t": ("Пять таблиц — ноль общей картины", "Бес кесте бар — ортақ көрініс жоқ"),
    "p_stats": ([("5", "подразделений АТУ ведут учёт в отдельных таблицах"), ("1,05 млрд т", "пищевых отходов в мире за 2022 год (UNEP, 2024)"), ("0", "общего реестра, аналитики причин и данных для ESG")],
                [("5", "АТУ бөлімшесі есепті бөлек кестелерде жүргізеді"), ("1,05 млрд т", "2022 жылы әлемдегі тамақ қалдығы (UNEP, 2024)"), ("0", "ортақ тізілім, себеп талдауы және ESG дерегі")]),
    "p_users_t": ("Кому это нужно", "Бұл кімге керек"),
    "p_users": ([("Сотрудник", "Запись за 4 действия с телефона"), ("Проверяющий", "Месячный отчёт: принять или вернуть"), ("Руководство", "Только принятые данные"), ("Студент", "Меню и бронь обеда")],
                [("Қызметкер", "Телефоннан 4 әрекетпен жазба"), ("Тексеруші", "Айлық есеп: қабылдау не қайтару"), ("Басшылық", "Тек қабылданған дерек"), ("Студент", "Мәзір және түскі ас броны")]),
    "p_note": ("Объём отходов по АТУ не предоставлен — его должна измерить система.", "АТУ бойынша қалдық көлемі берілмеген — оны жүйе өлшеуі тиіс."),
    "a_k": ("Анализ", "Талдау"), "a_t": ("Аналоги и наше отличие", "Аналогтар және біздің айырмашылық"),
    "a_cols": (["Без оборудования", "Формы таблиц АТУ", "Проверка отчётов", "Казахский язык", "Предзаказ студентов"],
               ["Жабдықсыз", "АТУ кесте формалары", "Есепті тексеру", "Қазақ тілі", "Студент тапсырысы"]),
    "a_rows": ([("Leanpath", [0, 0, 0, 0, 0]), ("Winnow", [0, 0, 0, 0, 0]), ("Общая таблица", [1, 1, 0, 1, 0]), ("Qaldyq", [1, 1, 1, 1, 1])],
               [("Leanpath", [0, 0, 0, 0, 0]), ("Winnow", [0, 0, 0, 0, 0]), ("Ортақ кесте", [1, 1, 0, 1, 0]), ("Qaldyq", [1, 1, 1, 1, 1])]),
    "a_note": ("Мы не заявляем, что первые. Leanpath и Winnow сильнее в автоматическом взвешивании и распознавании; цены в Казахстане не запрашивались.",
               "Біз бірінші деп мәлімдемейміз. Leanpath пен Winnow автоматты өлшеу мен тануда күштірек; Қазақстандағы бағасы сұралмаған."),
    "s_k": ("Решение", "Шешім"), "s_t": ("Одна цепочка вместо разрозненных таблиц", "Бөлек кестелердің орнына бір тізбек"),
    "s_steps": ([("Отходы", "Измерение: вид, кг или л, способ, этап"), ("Причина", "Мнение сотрудника и статистика — раздельно"), ("Рекомендация", "Прогноз спроса и объём приготовления"),
                 ("Действие", "Мероприятие утверждает руководство"), ("Выполнение", "Ответственный, срок, контроль"), ("Результат", "Показатели до и после")],
                [("Қалдық", "Өлшем: түрі, кг не л, тәсіл, кезең"), ("Себеп", "Қызметкер пікірі мен статистика — бөлек"), ("Ұсыныс", "Сұраныс болжамы және дайындау көлемі"),
                 ("Әрекет", "Іс-шараны басшылық бекітеді"), ("Орындау", "Жауапты, мерзім, бақылау"), ("Нәтиже", "Көрсеткіштер: дейін және кейін")]),
    "s_note": ("Изменение показателя не выдаётся за доказанный эффект: система показывает, что мешает сравнению.", "Көрсеткіштің өзгеруі дәлелденген әсер ретінде берілмейді: жүйе салыстыруға не кедергі екенін көрсетеді."),
    "c_k": ("Работающий цикл", "Жұмыс істейтін цикл"), "c_t": ("От формы до квартального отчёта", "Формадан тоқсандық есепке дейін"),
    "c_stats": ([("4", "действия на одну запись"), ("5", "организаций по образцам АТУ"), ("105", "автоматических проверок пройдено"), ("3", "графика на обзоре")],
                [("4", "әрекет — бір жазбаға"), ("5", "ұйым АТУ үлгісі бойынша"), ("105", "автоматты тексеру өтті"), ("3", "диаграмма шолуда")]),
    "c_flow": (["Форма", "Проверка", "Реестр", "Аналитика", "XLSX / PDF"], ["Форма", "Тексеру", "Тізілім", "Талдау", "XLSX / PDF"]),
    "chart_types": ("Структура принятых отходов, кг (демо)", "Қабылданған қалдық құрамы, кг (демо)"),
    "st_k": ("Студенты", "Студенттер"), "st_t": ("Меню и предзаказ в телефоне", "Мәзір мен тапсырыс телефонда"),
    "st_feats": ([("Меню без входа", "Регистрация даёт только роль студента"), ("Честный лимит", "Последняя порция — одному покупателю"), ("Код и QR", "Выдача и продажа — ровно один раз"),
                  ("Без онлайн-оплаты", "Бронь — это не оплата"), ("Офлайн", "Сохранённое меню с временем, без брони"), ("Один движок", "Сайт, Mini App и бот — одни правила")],
                 [("Кірусіз мәзір", "Тіркелу тек студент рөлін береді"), ("Әділ шек", "Соңғы порция — бір адамға"), ("Код және QR", "Беру мен сатылым — бір рет қана"),
                  ("Онлайн төлемсіз", "Бронь — төлем емес"), ("Офлайн", "Сақталған мәзір уақытымен, броньсыз"), ("Бір қозғалтқыш", "Сайт, Mini App, бот — бір ереже")]),
    "ar_k": ("Технология", "Технология"), "ar_t": ("Один сервер, одна база, проверяемые правила", "Бір сервер, бір база, тексерілетін ережелер"),
    "ar_clients": (["Сотрудник", "Проверяющий", "Студент · PWA", "Telegram"], ["Қызметкер", "Тексеруші", "Студент · PWA", "Telegram"]),
    "ar_mods": (["Отчёты и реестр", "Меню и заказы", "Склад и финансы", "Мероприятия", "Прогноз", "Уведомления"], ["Есеп және тізілім", "Мәзір мен тапсырыс", "Қойма мен қаржы", "Іс-шаралар", "Болжам", "Хабарламалар"]),
    "ar_server": ("Python · стандартная библиотека · права на сервере", "Python · стандартты кітапхана · құқық серверде"),
    "ar_db": ("SQLite · миграции без потери данных", "SQLite · деректі жоғалтпайтын миграция"),
    "ar_facts": ([("Деньги", "в целых тиынах"), ("Запасы", "средневзвешенная стоимость"), ("Закупка", "не расход — расход при использовании"), ("Повтор запроса", "не создаёт дубля")],
                 [("Ақша", "бүтін тиынмен"), ("Қор", "орташа өлшенген құн"), ("Сатып алу", "шығын емес — жұмсалғанда шығын"), ("Қайталанған сұрау", "көшірме жасамайды")]),
    "ml_k": ("Прогноз спроса", "Сұраныс болжамы"), "ml_t": ("ML не считается лучшим заранее", "ML алдын ала ең жақсы деп саналмайды"),
    "ml_chart": ("Средняя ошибка, порций (проверка на последних 3 неделях, демо)", "Орташа қате, порция (соңғы 3 аптада тексеру, демо)"),
    "ml_names": ({"existing": "Медиана (текущее)", "weekday": "По дню недели", "ml": "Градиентный бустинг"}, {"existing": "Медиана (қазіргі)", "weekday": "Апта күні бойынша", "ml": "Градиенттік бустинг"}),
    "ml_points": (["Прогнозируем общий спрос: столовая × блюдо × дата", "Предзаказы — нижняя граница, не прибавка", "Признаки только из прошлого; дни нехватки исключены из ошибки",
                   "Выбирается метод с меньшей ошибкой; план утверждает сотрудник"],
                  ["Болжанатыны — жалпы сұраныс: асхана × тағам × күн", "Алдын ала тапсырыс — төменгі шек, үстеме емес", "Белгілер тек өткеннен; тапшы күндер қатеге кірмейді",
                   "Қатесі аз әдіс таңдалады; жоспарды қызметкер бекітеді"]),
    "ml_warn": ("Модель обучена на синтетической демо-истории — это не результат эксплуатации.", "Модель синтетикалық демо тарихта оқытылған — бұл пайдалану нәтижесі емес."),
    "ac_k": ("Мероприятия", "Іс-шаралар"), "ac_t": ("От проблемы к измеренному результату", "Мәселеден өлшенген нәтижеге дейін"),
    "ac_steps": (["Предложено", "Утверждено", "Выполняется", "Оценивается", "Завершено"], ["Ұсынылды", "Бекітілді", "Орындалуда", "Бағалануда", "Аяқталды"]),
    "ac_cards": ([("До и после", "кг/100 порций, остатки, нехватка"), ("Сопоставимость", "меню, посещаемость, дни недели"), ("Компромисс", "отходов меньше, нехваток больше → пересмотр"),
                  ("Экономия", "расчётная отдельно от подтверждённой")],
                 [("Дейін және кейін", "кг/100 порция, қалдық, тапшылық"), ("Салыстырмалылық", "мәзір, келушілер, апта күндері"), ("Теңгерім", "қалдық азайып, тапшылық көбейсе → қайта қарау"),
                  ("Үнем", "есептік және расталған — бөлек")]),
    "e_k": ("Экономика и экология", "Экономика және экология"), "e_t": ("Сценарии на открытых допущениях", "Ашық жорамалдағы сценарийлер"),
    "e_chart": ("Чистая экономия в месяц, ₸ (сценарий)", "Айлық таза үнем, ₸ (сценарий)"),
    "e_cats": (["Осторожный · 5%", "Базовый · 15%", "Высокий · 25%"], ["Сақ · 5%", "Негізгі · 15%", "Жоғары · 25%"]),
    "e_payback": (["11,7 мес.", "2,3 мес.", "1,3 мес."], ["11,7 ай", "2,3 ай", "1,3 ай"]),
    "e_payback_t": ("Окупаемость", "Өтелу мерзімі"),
    "e_eco": ([("1,8 т", "отходов в год предотвращено"), ("4,5 т", "CO₂-экв. в год при 2,5 кг/кг"), ("≈20 ч", "труда в месяц при 300 записях")],
              [("1,8 т", "жылына алдын алынған қалдық"), ("4,5 т", "2,5 кг/кг кезінде жылдық CO₂-экв."), ("≈20 сағ", "300 жазбада айлық еңбек")]),
    "e_note": ("База: 1 000 кг/мес × 1 200 ₸/кг · CAPEX 350 000 ₸ · OPEX 30 000 ₸/мес. Это расчёты, а не результаты: пилот не проводился, источник CO₂-коэффициента не подтверждён.",
               "База: айына 1 000 кг × 1 200 ₸/кг · CAPEX 350 000 ₸ · OPEX айына 30 000 ₸. Бұлар — есеп, нәтиже емес: пилот өткізілмеген, CO₂ коэффициентінің дереккөзі расталмаған."),
    "pl_k": ("Внедрение", "Енгізу"), "pl_t": ("Пилот → АТУ → другие вузы", "Пилот → АТУ → басқа ЖОО"),
    "pl_weeks": ("Пилот в столовом комплексе · 6 недель", "Асхана кешеніндегі пилот · 6 апта"),
    "pl_bars": ([("Настройка и обучение", 0, 1), ("Базовый период", 1, 3), ("Мероприятие", 3, 5), ("Сравнение и отчёт", 5, 6)],
                [("Баптау және оқыту", 0, 1), ("Бастапқы кезең", 1, 3), ("Іс-шара", 3, 5), ("Салыстыру және есеп", 5, 6)]),
    "pl_week": ("нед.", "апта"),
    "pl_next": ([("Все 5 организаций АТУ", "≈ 2 месяца · справочники через интерфейс"), ("Другие вузы", "после пилота · спрос и тариф не исследованы")],
                [("АТУ-дың 5 ұйымы", "≈ 2 ай · анықтамалық интерфейстен"), ("Басқа ЖОО", "пилоттан кейін · сұраныс пен тариф зерттелмеген")]),
    "pl_risk": ("Риски: точность весов · нагрузка на сотрудников · сезонность · персональные данные · готовность вузов платить",
                "Тәуекел: таразы дәлдігі · қызметкер жүктемесі · маусымдылық · дербес дерек · ЖОО-ның төлеуге дайындығы"),
    "t_k": ("Команда и запрос", "Команда және сұраныс"), "t_t": ("Что нам нужно для пилота", "Пилотқа не қажет"),
    "t_ask_t": ("Запрос", "Сұраныс"),
    "t_ask": (["1 столовая на 6 недель", "Ответственный сотрудник и проверяющий", "Доступ к действующим таблицам", "Весы и телефон"],
              ["6 аптаға 1 асхана", "Жауапты қызметкер мен тексеруші", "Қолданыстағы кестелерге қолжетімділік", "Таразы және телефон"]),
    "t_decl": ("Декларация: основа прототипа подготовлена до хакатона; код, тексты и иллюстрации созданы с помощью генеративного ИИ. Все данные в демо — синтетические.",
               "Декларация: прототиптің негізі хакатонға дейін дайындалды; код, мәтін және иллюстрациялар генеративті ЖИ көмегімен жасалды. Демодағы барлық дерек — синтетикалық."),
    "demo": ("Демо-данные", "Демо дерек"),
}


class Deck:
    def __init__(self, lang, data):
        self.lang, self.i, self.data = lang, 0 if lang == "ru" else 1, data
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = Inches(13.333), Inches(7.5)
        self.img = OUT / ("img" if lang == "ru" else "img-kk")
        self.number = 0

    def t(self, key):
        return T[key][self.i]

    # ---- primitives
    def shape(self, page, kind, x, y, w, h, fill=None, line=None, radius=None, shadow=False):
        s = page.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
        if fill:
            s.fill.solid()
            s.fill.fore_color.rgb = rgb(fill)
        else:
            s.fill.background()
        if line:
            s.line.color.rgb = rgb(line)
            s.line.width = Pt(1)
        else:
            s.line.fill.background()
        if radius is not None and kind == MSO_SHAPE.ROUNDED_RECTANGLE:
            s.adjustments[0] = radius
        if not shadow:
            s.shadow.inherit = False
        return s

    def text(self, page, x, y, w, h, value, size=16, color=INK, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=1.1, gap=0):
        box = page.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        frame = box.text_frame
        frame.word_wrap, frame.vertical_anchor = True, anchor
        frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = Emu(0)
        for n, line in enumerate(value if isinstance(value, list) else [value]):
            p = frame.paragraphs[0] if n == 0 else frame.add_paragraph()
            p.alignment, p.line_spacing, p.space_after = align, spacing, Pt(gap)
            run = p.add_run()
            run.text = line
            run.font.size, run.font.bold, run.font.name, run.font.color.rgb = Pt(size), bold, FONT, rgb(color)
        return box

    def page(self, kicker, title, dark=False):
        self.number += 1
        page = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        page.background.fill.solid()
        page.background.fill.fore_color.rgb = rgb(DEEP if dark else PAPER)
        if not dark:
            self.shape(page, MSO_SHAPE.RECTANGLE, 0, 0, 0.16, 7.5, fill=GREEN)
            self.shape(page, MSO_SHAPE.OVAL, 11.6, -1.6, 3.4, 3.4, fill=MINT)
        self.shape(page, MSO_SHAPE.ROUNDED_RECTANGLE, 0.7, 0.5, 0.42 + 0.105 * len(kicker), 0.34, fill=LIME if dark else MINT, radius=0.5)
        self.text(page, 0.7, 0.5, 0.42 + 0.105 * len(kicker), 0.34, kicker.upper(), 10.5, DEEP if dark else GREEN, True, PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE)
        self.text(page, 0.7, 1.0, 11.2, 0.9, title, 32, WHITE if dark else INK, True)
        self.text(page, 12.1, 7.0, 0.9, 0.3, f"{self.number:02d} / 12", 10, LIME if dark else MUTED, False, PP_ALIGN.RIGHT)
        self.text(page, 0.7, 7.0, 4, 0.3, "qaldyq.  ·  NOVA", 10, LIME if dark else MUTED, True)
        return page

    def card(self, page, x, y, w, h, fill=CARD, line=LINE):
        return self.shape(page, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h, fill=fill, line=line, radius=0.08)

    def stat(self, page, x, y, w, h, big, label, accent=GREEN, fill=CARD, big_color=None, label_color=MUTED, size=40):
        self.card(page, x, y, w, h, fill=fill, line=None if fill != CARD else LINE)
        self.shape(page, MSO_SHAPE.RECTANGLE, x + 0.3, y + 0.32, 0.5, 0.07, fill=accent)
        big_h = size * 1.2 / 72
        self.text(page, x + 0.3, y + 0.48, w - 0.6, big_h, big, size, big_color or accent, True, anchor=MSO_ANCHOR.TOP)
        self.text(page, x + 0.3, y + 0.52 + big_h, w - 0.6, h - big_h - 0.6, label, 12.5 if h > 1.5 else 11.5, label_color, anchor=MSO_ANCHOR.TOP)

    def badge(self, page, x, y, d, value, fill=GREEN, color=WHITE, size=14):
        self.shape(page, MSO_SHAPE.OVAL, x, y, d, d, fill=fill)
        self.text(page, x, y, d, d, value, size, color, True, PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE)

    def picture(self, page, name, x, y, w=None, h=None, frame=True):
        path = self.img / name
        if not path.exists():
            return
        pic = page.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(w) if w else None, Inches(h) if h else None)
        if frame:
            pic.line.color.rgb = rgb(LINE)
            pic.line.width = Pt(1.25)
        return pic

    def browser(self, page, name, x, y, w, crop_h=None):
        """Screenshot inside a minimal browser frame."""
        path = self.img / name
        if not path.exists():
            return
        from PIL import Image
        iw, ih = Image.open(path).size
        h = crop_h or w * ih / iw
        self.card(page, x - 0.08, y - 0.42, w + 0.16, h + 0.5, fill=CARD, line=LINE)
        for n, color in enumerate((CORAL, AMBER, LEAF)):
            self.shape(page, MSO_SHAPE.OVAL, x + 0.08 + n * 0.22, y - 0.27, 0.12, 0.12, fill=color)
        pic = page.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(w))
        if crop_h:
            visible = crop_h / (w * ih / iw)
            pic.crop_bottom = 1 - visible
            pic.height = Inches(crop_h)

    def phone(self, page, name, x, y, h):
        path = self.img / name
        if not path.exists():
            return
        from PIL import Image
        iw, ih = Image.open(path).size
        w = h * iw / ih
        self.shape(page, MSO_SHAPE.ROUNDED_RECTANGLE, x - 0.14, y - 0.14, w + 0.28, h + 0.28, fill=INK, radius=0.09)
        page.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(w), Inches(h))
        self.shape(page, MSO_SHAPE.ROUNDED_RECTANGLE, x + w / 2 - 0.35, y - 0.08, 0.7, 0.08, fill=INK, radius=0.5)
        return w

    def chart(self, page, kind, x, y, w, h, categories, series, colors, labels=True, number_format='#,##0', legend=False, font_size=11, gap=60):
        data = CategoryChartData()
        data.categories = categories
        for name, values in series:
            data.add_series(name, values)
        frame = page.shapes.add_chart(kind, Inches(x), Inches(y), Inches(w), Inches(h), data)
        chart = frame.chart
        chart.font.name, chart.font.size, chart.font.color.rgb = FONT, Pt(font_size), rgb(MUTED)
        chart.has_legend = legend
        chart.has_title = False
        if legend:
            chart.legend.position, chart.legend.include_in_layout = XL_LEGEND_POSITION.RIGHT, False
            chart.legend.font.size, chart.legend.font.name = Pt(font_size), FONT
        plot = chart.plots[0]
        if kind != XL_CHART_TYPE.DOUGHNUT:
            plot.gap_width = gap
            chart.value_axis.visible = False
            chart.value_axis.has_major_gridlines = False
            chart.category_axis.format.line.fill.background()
            chart.category_axis.tick_labels.font.size = Pt(font_size)
            chart.category_axis.tick_labels.font.color.rgb = rgb(INK)
        else:
            plot.first_slice_angle = 0
        for n, point in enumerate(plot.series[0].points):
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = rgb(colors[n % len(colors)])
            if kind == XL_CHART_TYPE.DOUGHNUT:
                point.format.line.color.rgb = rgb(PAPER)
                point.format.line.width = Pt(2)
        if labels:
            plot.has_data_labels = True
            dl = plot.data_labels
            dl.number_format, dl.number_format_is_linked = number_format, False
            dl.font.size, dl.font.bold, dl.font.name = Pt(font_size + 1), True, FONT
            dl.font.color.rgb = rgb(INK)
            if kind in (XL_CHART_TYPE.COLUMN_CLUSTERED, XL_CHART_TYPE.BAR_CLUSTERED):
                dl.position = XL_LABEL_POSITION.OUTSIDE_END
        return chart

    # ---- slides
    def s1(self):
        self.number += 1
        page = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        page.background.fill.solid()
        page.background.fill.fore_color.rgb = rgb(DEEP)
        self.shape(page, MSO_SHAPE.OVAL, 8.6, -2.2, 7.2, 7.2, fill=FOREST)
        self.shape(page, MSO_SHAPE.OVAL, 10.4, 3.9, 4.6, 4.6, fill=GREEN)
        self.shape(page, MSO_SHAPE.OVAL, 9.2, 1.4, 1.1, 1.1, fill=LIME)
        campus = ROOT / "static" / "campus-3d-v2.png"
        if campus.exists():
            page.shapes.add_picture(str(campus), Inches(8.3), Inches(0.9), Inches(5.4), Inches(5.4))
        self.shape(page, MSO_SHAPE.ROUNDED_RECTANGLE, 0.8, 0.8, 4.4, 0.4, fill=FOREST, radius=0.5)
        self.text(page, 0.8, 0.8, 4.4, 0.4, self.t("track").upper(), 11, LIME, True, PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE)
        self.text(page, 0.8, 1.55, 7.5, 1.5, "qaldyq.", 88, WHITE, True)
        self.text(page, 0.8, 3.15, 7.2, 1.2, self.t("subtitle"), 22, "CFE3C9")
        x = 0.8
        for n, step in enumerate(self.t("chain")):
            width = 0.32 + 0.12 * len(step)
            self.shape(page, MSO_SHAPE.ROUNDED_RECTANGLE, x, 4.55, width, 0.46, fill=LIME if n == 4 else FOREST, radius=0.5)
            self.text(page, x, 4.55, width, 0.46, step, 13, DEEP if n == 4 else WHITE, True, PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE)
            x += width + 0.08
            if n < 4:
                self.text(page, x - 0.04, 4.55, 0.24, 0.46, "→", 14, LIME, True, PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE)
                x += 0.22
        self.text(page, 0.8, 5.55, 2.6, 0.3, self.t("team").upper(), 11, LIME, True)
        self.text(page, 0.8, 5.85, 7.6, 0.4, "   ·   ".join(TEAM), 16, WHITE, True)
        self.text(page, 0.8, 6.35, 7.6, 0.4, self.t("case"), 12, "9FBFA6")

    def s2(self):
        page = self.page(self.t("p_k"), self.t("p_t"))
        accents = [GREEN, AMBER, CORAL]
        for n, (big, label) in enumerate(self.t("p_stats")):
            self.stat(page, 0.7 + n * 4.05, 2.05, 3.8, 2.15, big, label, accents[n], size=36)
        self.text(page, 0.7, 4.5, 6, 0.4, self.t("p_users_t"), 15, INK, True)
        icons = ["S", "R", "M", "St"]
        for n, (role, need) in enumerate(self.t("p_users")):
            x = 0.7 + n * 3.05
            self.card(page, x, 4.95, 2.85, 1.55)
            self.badge(page, x + 0.25, 5.18, 0.55, role[0], fill=MINT, color=GREEN, size=16)
            self.text(page, x + 0.95, 5.18, 1.8, 0.55, role, 14, INK, True, anchor=MSO_ANCHOR.MIDDLE)
            self.text(page, x + 0.25, 5.85, 2.4, 0.6, need, 12, MUTED)
        self.text(page, 0.7, 6.6, 11.5, 0.3, self.t("p_note"), 11, MUTED)

    def s3(self):
        page = self.page(self.t("a_k"), self.t("a_t"))
        cols, rows = self.t("a_cols"), self.t("a_rows")
        x0, w0, cw, top, rh = 0.7, 2.6, 1.9, 2.1, 0.78
        for c, name in enumerate(cols):
            self.text(page, x0 + w0 + c * cw, top, cw, 0.6, name, 12, MUTED, True, PP_ALIGN.CENTER, MSO_ANCHOR.BOTTOM)
        for r, (name, marks) in enumerate(rows):
            y = top + 0.75 + r * rh
            ours = name == "Qaldyq"
            self.card(page, x0, y, w0 + cw * len(cols), rh - 0.12, fill=GREEN if ours else CARD, line=None if ours else LINE)
            self.text(page, x0 + 0.3, y, w0 - 0.3, rh - 0.12, name, 15, WHITE if ours else INK, True, anchor=MSO_ANCHOR.MIDDLE)
            for c, mark in enumerate(marks):
                cx = x0 + w0 + c * cw + cw / 2 - 0.2
                self.badge(page, cx, y + (rh - 0.12) / 2 - 0.2, 0.4, "✓" if mark else "–", fill=(LIME if ours else MINT) if mark else ("1C6B53" if ours else "EEF1EA"),
                           color=DEEP if mark else (LIME if ours else "9AA88F"), size=13)
        self.card(page, 0.7, 5.95, 12.1, 0.75, fill=MINT, line=None)
        self.text(page, 1.0, 5.95, 11.6, 0.75, self.t("a_note"), 12, FOREST, anchor=MSO_ANCHOR.MIDDLE)

    def s4(self):
        page = self.page(self.t("s_k"), self.t("s_t"))
        steps = self.t("s_steps")
        w, gap, y = 1.86, 0.17, 2.35
        for n, (name, desc) in enumerate(steps):
            x = 0.7 + n * (w + gap)
            last = n == len(steps) - 1
            self.card(page, x, y, w, 3.2, fill=GREEN if last else CARD, line=None if last else LINE)
            self.badge(page, x + 0.25, y + 0.3, 0.62, f"{n + 1:02d}", fill=LIME if last else MINT, color=DEEP if last else GREEN, size=14)
            self.text(page, x + 0.25, y + 1.15, w - 0.35, 0.5, name, 14, WHITE if last else INK, True)
            self.text(page, x + 0.25, y + 1.7, w - 0.45, 1.4, desc, 12, "D7EBCF" if last else MUTED)
            if not last:
                self.text(page, x + w - 0.05, y + 1.35, gap + 0.1, 0.4, "›", 22, LEAF, True, PP_ALIGN.CENTER)
        self.shape(page, MSO_SHAPE.RECTANGLE, 0.7, 5.95, 0.07, 0.6, fill=AMBER)
        self.text(page, 0.95, 5.95, 11.6, 0.6, self.t("s_note"), 13, INK, anchor=MSO_ANCHOR.MIDDLE)

    def s5(self):
        page = self.page(self.t("c_k"), self.t("c_t"))
        for n, (big, label) in enumerate(self.t("c_stats")):
            x, y = 0.7 + (n % 2) * 2.45, 2.05 + (n // 2) * 1.75
            self.stat(page, x, y, 2.3, 1.6, big, label, [GREEN, LEAF, AMBER, GREEN][n], size=34)
        flow = self.t("c_flow")
        x = 0.7
        for n, step in enumerate(flow):
            self.shape(page, MSO_SHAPE.CHEVRON if n else MSO_SHAPE.PENTAGON, x, 5.75, 1.1, 0.62, fill=GREEN if n == len(flow) - 1 else LEAF if n % 2 else FOREST)
            self.text(page, x + 0.22, 5.75, 0.72, 0.62, step, 8.5, WHITE, True, PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE)
            x += 0.96
        self.browser(page, "dashboard.png", 5.95, 2.45, 6.85, crop_h=3.85)
        self.text(page, 5.95, 6.45, 6.8, 0.3, self.t("demo"), 10, MUTED, False, PP_ALIGN.RIGHT)

    def s6(self):
        page = self.page(self.t("st_k"), self.t("st_t"))
        feats = self.t("st_feats")
        for n, (title, desc) in enumerate(feats):
            x, y = 0.7 + (n % 2) * 3.85, 2.05 + (n // 2) * 1.55
            self.card(page, x, y, 3.65, 1.38)
            self.badge(page, x + 0.25, y + 0.3, 0.52, str(n + 1), fill=[GREEN, LEAF, AMBER, CORAL, FOREST, GREEN][n], size=14)
            self.text(page, x + 0.95, y + 0.25, 2.55, 0.45, title, 14, INK, True, anchor=MSO_ANCHOR.MIDDLE)
            self.text(page, x + 0.95, y + 0.72, 2.6, 0.6, desc, 11.5, MUTED)
        self.shape(page, MSO_SHAPE.OVAL, 8.75, 1.75, 4.5, 4.5, fill=MINT)
        self.phone(page, "student.png", 9.55, 1.55, 5.2)

    def s7(self):
        page = self.page(self.t("ar_k"), self.t("ar_t"))
        clients = self.t("ar_clients")
        for n, name in enumerate(clients):
            self.card(page, 0.7, 2.05 + n * 0.92, 2.3, 0.72, fill=MINT, line=None)
            self.text(page, 0.7, 2.05 + n * 0.92, 2.3, 0.72, name, 13, FOREST, True, PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE)
            self.text(page, 3.02, 2.05 + n * 0.92, 0.45, 0.72, "→", 18, LEAF, True, PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE)
        self.card(page, 3.5, 1.95, 5.3, 3.75, fill=DEEP, line=None)
        self.text(page, 3.8, 2.12, 4.8, 0.4, self.t("ar_server"), 11.5, LIME, True)
        for n, name in enumerate(self.t("ar_mods")):
            x, y = 3.8 + (n % 2) * 2.4, 2.65 + (n // 2) * 0.92
            self.card(page, x, y, 2.25, 0.75, fill=FOREST, line=None)
            self.text(page, x, y, 2.25, 0.75, name, 12.5, WHITE, True, PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE)
        self.text(page, 3.5, 5.72, 5.3, 0.4, "↓", 18, LEAF, True, PP_ALIGN.CENTER)
        self.shape(page, MSO_SHAPE.CAN, 4.0, 6.05, 4.3, 0.82, fill=GREEN)
        self.text(page, 4.1, 6.25, 4.1, 0.55, self.t("ar_db"), 11, WHITE, True, PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE)
        for n, (title, desc) in enumerate(self.t("ar_facts")):
            y = 1.95 + n * 1.2
            self.card(page, 9.2, y, 3.6, 1.05)
            self.shape(page, MSO_SHAPE.RECTANGLE, 9.2, y + 0.18, 0.07, 0.7, fill=[GREEN, LEAF, AMBER, CORAL][n])
            self.text(page, 9.5, y + 0.15, 3.2, 0.4, title, 14, INK, True)
            self.text(page, 9.5, y + 0.55, 3.2, 0.45, desc, 11.5, MUTED)

    def s8(self):
        page = self.page(self.t("ml_k"), self.t("ml_t"))
        names, methods = self.t("ml_names"), self.data["methods"]
        order = [k for k in ("existing", "weekday", "ml") if k in methods]
        best = min(order, key=lambda k: methods[k])
        self.card(page, 0.7, 2.0, 6.4, 4.2)
        self.text(page, 1.0, 2.2, 5.9, 0.5, self.t("ml_chart"), 12, MUTED, True)
        self.chart(page, XL_CHART_TYPE.BAR_CLUSTERED, 0.9, 2.7, 6.0, 3.3, [names[k] for k in order], [("MAE", [methods[k] for k in order])],
                   [GREEN if k == best else "BFD3B4" for k in order], number_format="0.00", font_size=12, gap=45)
        for n, point in enumerate(self.t("ml_points")):
            y = 2.0 + n * 0.9
            self.badge(page, 7.5, y + 0.05, 0.5, str(n + 1), fill=MINT, color=GREEN, size=13)
            self.text(page, 8.2, y, 4.6, 0.8, point, 13.5, INK, anchor=MSO_ANCHOR.MIDDLE)
        self.card(page, 7.5, 5.65, 5.3, 0.85, fill="FFF4E0", line=None)
        self.text(page, 7.75, 5.65, 4.9, 0.85, self.t("ml_warn"), 12, "8A5A12", True, anchor=MSO_ANCHOR.MIDDLE)

    def s9(self):
        page = self.page(self.t("ac_k"), self.t("ac_t"))
        steps = self.t("ac_steps")
        self.shape(page, MSO_SHAPE.RECTANGLE, 1.0, 2.33, 11.4, 0.06, fill=LINE)
        for n, name in enumerate(steps):
            x = 1.0 + n * 2.85
            self.badge(page, x - 0.25, 2.1, 0.5, str(n + 1), fill=GREEN if n < 4 else LIME, color=WHITE if n < 4 else DEEP, size=13)
            self.text(page, x - 1.0, 2.68, 2.0, 0.4, name, 12.5, INK, True, PP_ALIGN.CENTER)
        for n, (title, desc) in enumerate(self.t("ac_cards")):
            x, y = 0.7 + (n % 2) * 2.95, 3.35 + (n // 2) * 1.65
            self.card(page, x, y, 2.8, 1.5, fill=[CARD, CARD, "FFF4E0", MINT][n], line=LINE if n < 2 else None)
            self.text(page, x + 0.25, y + 0.22, 2.4, 0.45, title, 14, INK, True)
            self.text(page, x + 0.25, y + 0.68, 2.4, 0.75, desc, 11.5, MUTED)
        self.browser(page, "action.png", 6.8, 3.75, 6.0, crop_h=2.85)

    def s10(self):
        page = self.page(self.t("e_k"), self.t("e_t"))
        self.card(page, 0.7, 2.0, 6.6, 4.0)
        self.text(page, 1.0, 2.2, 6.0, 0.4, self.t("e_chart"), 12, MUTED, True)
        self.chart(page, XL_CHART_TYPE.COLUMN_CLUSTERED, 0.9, 2.6, 6.2, 2.75, self.t("e_cats"), [("₸", [30000, 150000, 270000])], ["BFD3B4", GREEN, LEAF],
                   number_format='#,##0" ₸"', font_size=11, gap=70)
        for n, value in enumerate(self.t("e_payback")):
            self.text(page, 1.1 + n * 2.0, 5.42, 1.8, 0.45, f"{self.t('e_payback_t')}: {value}", 11, FOREST, True, PP_ALIGN.CENTER)
        for n, (big, label) in enumerate(self.t("e_eco")):
            self.stat(page, 7.6, 2.0 + n * 1.36, 5.2, 1.22, big, label, [GREEN, LEAF, AMBER][n], size=28)
        self.text(page, 0.7, 6.2, 12.1, 0.6, self.t("e_note"), 10.5, MUTED)

    def s11(self):
        page = self.page(self.t("pl_k"), self.t("pl_t"))
        self.card(page, 0.7, 2.0, 12.1, 2.95)
        self.text(page, 1.0, 2.15, 8, 0.4, self.t("pl_weeks"), 14, INK, True)
        left, unit = 3.75, 1.45
        for week in range(6):
            self.text(page, left + week * unit, 2.6, unit, 0.3, f"{week + 1} {self.t('pl_week')}", 10, MUTED, True, PP_ALIGN.CENTER)
            self.shape(page, MSO_SHAPE.RECTANGLE, left + week * unit, 2.95, 0.01, 1.85, fill=LINE)
        for n, (name, start, end) in enumerate(self.t("pl_bars")):
            y = 3.0 + n * 0.45
            self.text(page, 1.0, y, 2.7, 0.38, name, 12, INK, anchor=MSO_ANCHOR.MIDDLE)
            self.shape(page, MSO_SHAPE.ROUNDED_RECTANGLE, left + start * unit + 0.05, y + 0.04, (end - start) * unit - 0.1, 0.3, fill=[FOREST, GREEN, LEAF, AMBER][n], radius=0.5)
        for n, (title, desc) in enumerate(self.t("pl_next")):
            x = 0.7 + n * 6.15
            self.card(page, x, 5.15, 5.95, 1.1, fill=DEEP if n else GREEN, line=None)
            self.text(page, x + 0.3, 5.25, 5.4, 0.45, title, 15, WHITE, True)
            self.text(page, x + 0.3, 5.7, 5.4, 0.45, desc, 11.5, "D7EBCF")
        self.text(page, 0.7, 6.4, 12.1, 0.4, self.t("pl_risk"), 11, MUTED)

    def s12(self):
        page = self.page(self.t("t_k"), self.t("t_t"), dark=True)
        self.shape(page, MSO_SHAPE.OVAL, 10.2, 4.6, 4.4, 4.4, fill=FOREST)
        for n, name in enumerate(TEAM):
            x = 0.7 + n * 2.6
            self.card(page, x, 2.15, 2.4, 2.75, fill=FOREST, line=None)
            initials = "".join(part[0] for part in name.split()[:2])
            self.badge(page, x + 0.7, 2.45, 1.0, initials, fill=LIME, color=DEEP, size=22)
            surname, first = name.split()[0], " ".join(name.split()[1:])
            self.text(page, x + 0.15, 3.65, 2.1, 0.45, surname, 15, WHITE, True, PP_ALIGN.CENTER)
            self.text(page, x + 0.15, 4.08, 2.1, 0.4, first, 13, "CFE3C9", False, PP_ALIGN.CENTER)
        self.card(page, 8.65, 2.15, 4.15, 2.75, fill=LIME, line=None)
        self.text(page, 8.95, 2.35, 3.6, 0.45, self.t("t_ask_t").upper(), 12, DEEP, True)
        self.text(page, 8.95, 2.85, 3.65, 2.0, ["✓  " + item for item in self.t("t_ask")], 13.5, DEEP, True, gap=7)
        self.text(page, 0.7, 5.35, 9.3, 0.9, self.t("t_decl"), 11, "9FBFA6")

    def build(self):
        for n in range(1, 13):
            getattr(self, f"s{n}")()
        path = OUT / f"Qaldyq-NOVA-{self.lang}.pptx"
        self.prs.save(path)
        return path


if __name__ == "__main__":
    data = load_data()
    for lang in (sys.argv[1:] or ["ru", "kk"]):
        print(Deck(lang, data).build())
