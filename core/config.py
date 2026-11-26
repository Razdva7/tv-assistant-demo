"""Сводка журнала итогов для руководителя магазина: сколько консультаций, чем закончились,
чего не хватило в магазине (неудовлетворённый спрос). Без Streamlit — проверяется тестами."""
from __future__ import annotations

import json

import pandas as pd

from .rules import cond_labels


def _need(conditions: str) -> str:
    try:
        cond = json.loads(conditions)
    except (TypeError, ValueError):
        return ""
    return ", ".join(label for _, label in cond_labels(cond))


def summarize(log: pd.DataFrame, top: int = 3) -> dict:
    total = len(log)
    if not total:
        return {"total": 0}
    out = log["outcome"]
    res = {
        "total": total,
        "shown_share": round((out == "shown").mean() * 100),
        "no_match": int((out == "no_match").sum()),
        "wrong": int((out == "wrong").sum()),
    }
    if "terms_total" in log and log["terms_total"].max() > 0:
        res["terms_avg"] = round(float(log["terms_done"].mean()), 1)
        res["terms_total"] = int(log["terms_total"].max())
    unmet = log.loc[out == "no_match", "conditions"].map(_need)
    unmet = unmet[unmet != ""].value_counts().head(top)
    res["unmet"] = list(unmet.items())
    reasons = log.loc[(out == "wrong") & log["reason"].notna(), "reason"].value_counts().head(top)
    res["wrong_reasons"] = list(reasons.items())
    return res
