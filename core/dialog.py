"""Ответ помощника в диалоге: одно короткое окно «что делать сейчас».

Продавец говорит или пишет — помощник отвечает: что понял, что показать, что уточнить, что предложить.
Подбор и тексты — только из правил и таблиц экспертов; модель лишь переводит фразу в условия.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import knowledge
from .rules import Pick, client_diff, client_facts, count_matches, missing_questions, recommend, rub


@dataclass
class Reply:
    understood: str                  # «телевизор — 55–65″, не OLED»
    action: str                      # главная строка «Сейчас: …» (markdown)
    reasons: list[str]               # 1–2 причины + честный минус для главной модели
    alts: list[str]                  # ещё 2 варианта, по строке
    diff: str | None                 # чем отличаются первые две
    asks: list[str]                  # ключи вопросов, которые стоит уточнить (не больше 2)
    addons: list[dict]               # сопутствующее по названной потребности
    picks: list[Pick] = field(default_factory=list)       # всё, что показано (для «Подробнее»)
    warehouse: list[Pick] = field(default_factory=list)
    found: int = 0
    exact: bool = True               # False — подборка из ближайших с компромиссом


def merge_cond(old: dict, new: dict) -> dict:
    """Новая фраза дополняет условия. Противоположные условия заменяют друг друга."""
    out = dict(old)
    if "panel" in new and out.get("panel_not") == new["panel"]:
        out.pop("panel_not")
    if "panel_not" in new and out.get("panel") == new["panel_not"]:
        out.pop("panel")
    out.update(new)
    if out.get("price_min") and out.get("price_max") and out["price_min"] > out["price_max"]:
        out.pop("price_min") if "price_max" in new else out.pop("price_max")
    return out


def _where(p: Pick) -> str:
    return "в зале" if p.where == "store" else "со склада, 2–3 дня"


def _plus(p: Pick) -> list[str]:
    """Причины без повторов того, что и так видно: размер и цена стоят в заголовке."""
    out = [w for w in p.why if not w.endswith("нужный размер") and not w.startswith("В бюджете")]
    return out or [client_facts(p.row)[1]]


def _minus(p: Pick) -> str | None:
    if not p.trade:
        return None
    t = p.trade[0]
    if t.startswith("Ослаблено: "):
        return "Компромисс: " + t[len("Ослаблено: "):]
    return "Минус: " + t[0].lower() + t[1:]


def _short(p: Pick) -> str:
    return f"{p.title} — {rub(p.row.price)}"


def build_reply(cat: pd.DataFrame, cond: dict, store: str, skip_asks=(), category: str = "tv") -> Reply:
    asks = [q for q in missing_questions(cond, limit=4) if q not in skip_asks][:2]
    addons = knowledge.addons(category, cond)
    understood = knowledge.need_phrase(cond)
    if not cond:
        return Reply(understood="", action="Спросите клиента, для чего и куда нужен телевизор.", reasons=[],
                     alts=[], diff=None, asks=asks, addons=[])
    res = recommend(cat, cond, store)
    found = count_matches(cat, cond, store)
    picks, exact = (res.picks, True) if res.picks else (res.nearest, False)
    if not picks and res.warehouse:
        picks, exact = res.warehouse, True
    if not picks:
        return Reply(understood=understood, action="Под эти условия моделей нет даже с компромиссом. "
                     "Уберите лишнее условие — чаще всего бюджет или тип матрицы.", reasons=[], alts=[],
                     diff=None, asks=asks, addons=addons, warehouse=res.warehouse, found=0, exact=False)
    main = picks[0]
    head = f"покажите **{main.title}**, {_where(main)}"  # цена — только в карточке, не дублируем
    if exact:
        action = head[0].upper() + head[1:]
    else:
        action = f"Под все условия нет — мешает **{res.blocker or 'сочетание условий'}**. Ближайшее: {head}"
    reasons = _plus(main)[:2]
    if _minus(main):
        reasons.append(_minus(main))
    diff = client_diff([picks[0].row, picks[1].row]) if len(picks) > 1 else []
    return Reply(understood=understood, action=action, reasons=reasons, alts=[_short(p) for p in picks[1:3]],
                 diff=diff[0] if diff else None, asks=asks, addons=addons, picks=picks,
                 warehouse=res.warehouse if res.picks else [], found=found, exact=exact)


def summary_text(cond: dict, reply: Reply | None) -> str:
    """Резюме для клиента: что поняли и что советуем."""
    s = knowledge.summary(cond)
    if reply and reply.picks:
        p = reply.picks[0]
        s += f" Из подходящих советую {p.title} за {rub(p.row.price)}."
    return s
