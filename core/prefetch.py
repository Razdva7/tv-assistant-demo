"""Таблица знаний для консультации: возражения, сопутствующие товары, «не забыть сказать».

Знания лежат в CSV-файлах data/knowledge/<категория>_*.csv. Их правят эксперты-продавцы
без программиста: строка = один ответ, одна подсказка или один пункт. Код только читает таблицы.

Условие сопутствующего товара (колонка trigger) записывается так:
  wall_mount        — условие есть в запросе
  use=games         — условие равно значению
  diag_min>=65      — число в условии не меньше значения
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from .config import ROOT
from .rules import cond_labels

KNOWLEDGE_DIR = ROOT / "data" / "knowledge"


def _read(category: str, name: str) -> list[dict]:
    path = KNOWLEDGE_DIR / f"{category}_{name}.csv"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def objections(category: str) -> list[dict]:
    return _read(category, "objections")


def terms(category: str) -> list[dict]:
    return _read(category, "terms")


_TRIGGER = re.compile(r"^\s*(\w+)\s*(?:(>=|<=|=)\s*(.+?))?\s*$")


def trigger_matches(trigger: str, cond: dict) -> bool:
    m = _TRIGGER.match(trigger or "")
    if not m:
        return False
    key, op, val = m.groups()
    have = cond.get(key)
    if have in (None, False, ""):
        return False
    if op is None:
        return True
    if op == "=":
        return str(have) == val
    try:
        have_n, val_n = float(have), float(val)
    except (TypeError, ValueError):
        return False
    return have_n >= val_n if op == ">=" else have_n <= val_n


def addons(category: str, cond: dict) -> list[dict]:
    """Сопутствующее — только при названной потребности, с причиной и вопросом клиенту."""
    return [a for a in _read(category, "addons") if trigger_matches(a.get("trigger", ""), cond)]


def need_phrase(cond: dict, noun: str = "телевизор") -> str:
    """Потребность клиента его словами: «телевизор — для игр, диагональ 55–65″, до 100 000 ₽»."""
    use_phrase = {"games": "для игр", "movies": "для кино и сериалов", "sport": "для спорта", "tv": "для ТВ и YouTube"}
    parts = [use_phrase.get(cond.get("use"), label) if key == "use" else label[0].lower() + label[1:]
             for key, label in cond_labels(cond)]
    return f"{noun} — " + ", ".join(parts) if parts else ""


def summary(cond: dict, noun: str = "телевизор") -> str:
    """Фраза для резюме потребности вслух: «Правильно понимаю: нужен телевизор …?»"""
    need = need_phrase(cond, noun)
    return f"Правильно понимаю: нужен {need}?" if need else ""
