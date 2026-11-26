"""Эталонный набор фраз продавца. Запускается перед каждым выпуском правил.

Тест падает, если:
- хоть одно условие перевёрнуто (например, «не OLED» стало «нужен OLED»);
- полностью верно разобрано меньше PASS_RATE фраз.
Новую фразу эксперт добавляет строкой в golden_phrases.csv: текст, ожидаемые условия в JSON, тип.
"""
import csv
import json
from pathlib import Path

from core.parser import parse_rules

PASS_RATE = 0.90
GOLDEN = Path(__file__).with_name("golden_phrases.csv")


def load():
    with open(GOLDEN, encoding="utf-8") as f:
        return [(r["text"], json.loads(r["expected"]), r["kind"]) for r in csv.DictReader(f)]


def got_of(text):
    return {i["k"]: i["v"] for i in parse_rules(text)}


def test_no_inverted_conditions():
    """Отрицание не должно превращаться в требование."""
    bad = []
    for text, exp, _ in load():
        got = got_of(text)
        if got.get("panel") and got.get("panel") == exp.get("panel_not"):
            bad.append(text)
        if "panel_not" not in exp and got.get("panel_not") and got.get("panel_not") == exp.get("panel"):
            bad.append(text)
        if exp == {} and got:
            bad.append(text)
    assert not bad, f"Перевёрнутые или лишние условия: {bad}"


def test_golden_pass_rate():
    rows = load()
    failed = [(t, exp, got_of(t)) for t, exp, _ in rows if got_of(t) != exp]
    rate = 1 - len(failed) / len(rows)
    report = "\n".join(f"  «{t}»: ждали {e}, получили {g}" for t, e, g in failed)
    assert rate >= PASS_RATE, f"Разобрано верно {rate:.0%} < {PASS_RATE:.0%}:\n{report}"
