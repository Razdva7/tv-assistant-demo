"""Реестр категорий. Новая категория = описание здесь + каталог + правила подбора.

Готова только категория «Телевизоры». Для остальных хранится превью: какие вопросы
задаст помощник, пример голосовой фразы и что будет в сравнении. Подбора для них нет,
потому что нет каталога и проверенных правил — выдуманные товары не показываем.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .rules import QUESTIONS as TV_QUESTIONS


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    icon: str
    ready: bool
    questions: list[str]                  # вопросы покупателю (для превью и подсказки)
    voice_example: str                    # пример выжимки голосом
    compare: list[str]                    # что будет в сравнении
    presets: dict[str, dict] = field(default_factory=dict)  # частые запросы -> условия подбора


TV_PRESETS = {
    "🎮 Для PS5 / Xbox": {"use": "games", "min_refresh": 120, "diag_min": 55, "diag_max": 65},
    "🍳 На кухню, маленький": {"diag_min": 32, "diag_max": 43},
    "🎬 Кино в тёмной комнате": {"use": "movies", "room": "dark"},
    "💰 Недорогой, до 30 тыс.": {"price_max": 30000},
    "👵 Родителям, простой": {"use": "tv", "diag_min": 43, "diag_max": 50, "price_max": 40000},
}

CATEGORIES: dict[str, Category] = {
    "tv": Category(
        id="tv", name="Телевизоры", icon="📺", ready=True,
        questions=[q["label"] for q in TV_QUESTIONS.values()],
        voice_example="«шестьдесят пять дюймов, для плейстейшн, до ста тысяч»",
        compare=["Диагональ", "Матрица", "Разрешение", "Частота", "HDMI 2.1", "Яркость", "Платформа", "Цена"],
        presets=TV_PRESETS,
    ),
    "fridge": Category(
        id="fridge", name="Холодильники", icon="🧊", ready=False,
        questions=["Сколько человек в семье", "Место под холодильник: ширина и высота",
                   "Нужна ли No Frost", "Встроенный или отдельно стоящий", "Бюджет"],
        voice_example="«семья из четырёх, ниша шестьдесят сантиметров, ноу фрост, до шестидесяти тысяч»",
        compare=["Объём", "Габариты", "No Frost", "Класс энергии", "Уровень шума", "Цена"],
    ),
    "washer": Category(
        id="washer", name="Стиральные машины", icon="🌀", ready=False,
        questions=["Сколько стирают за раз", "Глубина места", "Нужна ли сушка", "Бюджет"],
        voice_example="«узкая до сорока пяти сантиметров, на семь килограмм, с паром»",
        compare=["Загрузка", "Глубина", "Отжим", "Сушка", "Уровень шума", "Цена"],
    ),
    "phone": Category(
        id="phone", name="Смартфоны", icon="📱", ready=False,
        questions=["Android или iPhone", "Что важнее: камера, батарея, игры", "Размер экрана", "Бюджет"],
        voice_example="«андроид, хорошая камера и батарея, до тридцати тысяч»",
        compare=["Экран", "Камера", "Аккумулятор", "Память", "Процессор", "Цена"],
    ),
    "laptop": Category(
        id="laptop", name="Ноутбуки", icon="💻", ready=False,
        questions=["Для чего: учёба, работа, игры", "Нужно ли носить с собой", "Размер экрана", "Бюджет"],
        voice_example="«для учёбы, лёгкий, пятнадцать дюймов, до шестидесяти тысяч»",
        compare=["Процессор", "Память", "Накопитель", "Экран", "Вес", "Цена"],
    ),
    "vacuum": Category(
        id="vacuum", name="Пылесосы", icon="🧹", ready=False,
        questions=["Площадь и покрытие пола", "Есть ли животные", "Робот, вертикальный или обычный", "Бюджет"],
        voice_example="«робот, есть кошка, ламинат и ковры, до тридцати тысяч»",
        compare=["Тип", "Мощность всасывания", "Время работы", "Влажная уборка", "Шум", "Цена"],
    ),
}
