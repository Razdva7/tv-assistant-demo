"""Подбор телевизора по правилам. Языковая модель здесь не участвует:
одинаковые условия и остатки всегда дают одинаковый результат."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# ---------- Вопросы для кнопок ----------
QUESTIONS = {
    "use": {
        "label": "Для чего",
        "options": {"Кино и сериалы": "movies", "Игры (консоль)": "games", "ТВ и YouTube": "tv"},
    },
    "room": {
        "label": "Комната",
        "options": {"Светлая": "bright", "Тёмная": "dark"},
    },
    "distance": {
        "label": "До дивана",
        "options": {"до 2 м": (32, 50), "2–3 м": (55, 65), "больше 3 м": (65, 85)},
    },
    "budget": {
        "label": "Бюджет",
        "options": {"до 40 тыс.": 40000, "до 70 тыс.": 70000, "до 120 тыс.": 120000, "не важно": None},
    },
}

RES_ORDER = {"HD": 0, "Full HD": 1, "4K": 2}
USE_LABEL = {"movies": "кино и сериалы", "games": "игры", "sport": "спорт", "tv": "ТВ и YouTube"}
ROOM_LABEL = {"bright": "светлая комната", "dark": "тёмная комната"}
OVER_BUDGET_TOLERANCE = 0.10  # +10% к бюджету допускается только как названный компромисс


def rub(x: float) -> str:
    return f"{int(round(x)):,}".replace(",", "\u00a0") + "\u00a0₽"  # неразрывные пробелы: цена не рвётся на строки


def cond_labels(cond: dict) -> list[tuple[str, str]]:
    """Человекочитаемые чипы условий: [(ключ, подпись)]."""
    out = []
    dmin, dmax = cond.get("diag_min"), cond.get("diag_max")
    if dmin and dmax and dmin == dmax:
        out.append(("diag", f"Диагональ {dmin}″"))
    elif dmin or dmax:
        out.append(("diag", f"Диагональ {dmin or '…'}–{dmax or '…'}″"))
    if cond.get("price_min"):
        out.append(("price_min", f"От {rub(cond['price_min'])}"))
    if cond.get("price_max"):
        out.append(("price_max", f"До {rub(cond['price_max'])}"))
    if cond.get("use"):
        out.append(("use", f"Для: {USE_LABEL[cond['use']]}"))
    if cond.get("room"):
        out.append(("room", ROOM_LABEL[cond["room"]].capitalize()))
    if cond.get("panel"):
        out.append(("panel", f"Матрица {cond['panel']}"))
    if cond.get("panel_not"):
        out.append(("panel_not", f"Не {cond['panel_not']}"))
    if cond.get("resolution"):
        out.append(("resolution", f"Разрешение от {cond['resolution']}"))
    if cond.get("min_refresh"):
        out.append(("min_refresh", f"От {cond['min_refresh']} Гц"))
    if cond.get("smart_os"):
        out.append(("smart_os", f"Платформа {cond['smart_os']}"))
    if cond.get("width_max_cm"):
        out.append(("width_max_cm", f"Ширина до {cond['width_max_cm']} см"))
    if cond.get("wall_mount"):
        out.append(("wall_mount", "На стену"))
    return out


def clear_cond(cond: dict, key: str) -> None:
    if key == "diag":
        cond.pop("diag_min", None)
        cond.pop("diag_max", None)
    else:
        cond.pop(key, None)


# ---------- Обязательные условия ----------
def _mandatory_checks(cond: dict) -> dict:
    """Ключ условия -> функция-фильтр по строке каталога (без бюджета)."""
    checks = {}
    if cond.get("diag_min") or cond.get("diag_max"):
        lo, hi = cond.get("diag_min") or 0, cond.get("diag_max") or 999
        checks["diag"] = lambda r, lo=lo, hi=hi: lo <= r.diagonal_in <= hi
    if cond.get("resolution"):
        need = RES_ORDER[cond["resolution"]]
        checks["resolution"] = lambda r, need=need: RES_ORDER[r.resolution] >= need
    if cond.get("panel"):
        checks["panel"] = lambda r, p=cond["panel"]: r.panel == p
    if cond.get("panel_not"):
        checks["panel_not"] = lambda r, p=cond["panel_not"]: r.panel != p
    if cond.get("price_min"):
        checks["price_min"] = lambda r, lo=cond["price_min"]: r.price >= lo
    if cond.get("width_max_cm"):
        checks["width_max_cm"] = lambda r, w=cond["width_max_cm"]: r.width_cm <= w
    if cond.get("min_refresh"):
        checks["min_refresh"] = lambda r, hz=cond["min_refresh"]: r.refresh_hz >= hz
    return checks


def _passes(r, checks: dict, skip: str | None = None) -> bool:
    return all(f(r) for k, f in checks.items() if k != skip)


# ---------- Желательные условия и объяснения ----------
def _score(r, cond: dict) -> tuple[int, list[str], list[str]]:
    score, why, trade = 0, [], []
    use, room, os_ = cond.get("use"), cond.get("room"), cond.get("smart_os")
    if use == "games":
        if r.refresh_hz >= 120:
            score += 3
            why.append(f"{r.refresh_hz} Гц — плавная картинка в играх")
        else:
            trade.append("60 Гц — в играх плавность ниже")
        if r.hdmi21:
            score += 3
            why.append("HDMI 2.1 — консоль выдаст 120 кадров")
        else:
            trade.append("Нет HDMI 2.1 — консоль не выдаст 120 кадров")
    elif use == "movies":
        if r.panel in ("OLED", "Mini LED", "QLED"):
            score += {"OLED": 3, "Mini LED": 3, "QLED": 2}[r.panel]
            why.append({
                "OLED": "OLED — глубокий чёрный и контраст в кино",
                "Mini LED": "Mini LED — яркий HDR и высокий контраст",
                "QLED": "QLED — насыщенные цвета в фильмах",
            }[r.panel])
        else:
            trade.append("Обычная LED-матрица — контраст в кино ниже")
        if r.resolution == "4K":
            score += 1
    elif use == "sport":
        if r.refresh_hz >= 100:
            score += 3
            why.append(f"{r.refresh_hz} Гц — мяч и шайба без смазывания")
        else:
            trade.append("60 Гц — в быстрых сценах спорта картинка смазывается")
        if r.brightness_nits >= 400:
            score += 1
            why.append(f"Яркость {r.brightness_nits} нит — матч днём при свете")
    elif use == "tv":
        if r.smart_os != "Своя ОС":
            score += 1
            why.append(f"{r.smart_os} — YouTube и онлайн-кинотеатры из коробки")
        else:
            trade.append("Собственная ОС — меньше приложений")
    if room == "bright":
        if r.brightness_nits >= 500:
            score += 2
            why.append(f"Яркость {r.brightness_nits} нит — видно днём у окна")
        else:
            trade.append(f"Яркость {r.brightness_nits} нит — днём у окна блекнет")
    elif room == "dark":
        if r.panel == "OLED":
            score += 2
            why.append("OLED — идеальный чёрный в тёмной комнате")
        elif r.panel == "Mini LED":
            score += 1
            why.append("Mini LED — хороший контраст в темноте")
    if os_:
        if r.smart_os == os_:
            score += 1
            why.append(f"Платформа {os_}, как просил покупатель")
        else:
            trade.append(f"Платформа {r.smart_os}, а не {os_}")
    return score, why, trade


@dataclass
class Pick:
    row: pd.Series
    score: int
    why: list[str]
    trade: list[str]
    stock: int
    where: str  # "store" | "warehouse"
    relaxed: str | None = None

    @property
    def title(self) -> str:
        r = self.row
        return f"{r.brand} {r.model}, {r.diagonal_in}″"


@dataclass
class Result:
    picks: list[Pick]
    found_total: int  # сколько моделей в магазине прошло все обязательные условия
    warehouse: list[Pick] = field(default_factory=list)
    blocker: str | None = None  # какое условие отсекло всё (если подборка пуста)
    nearest: list[Pick] = field(default_factory=list)


def _make_pick(r, cond, store_col, over_budget=False, relaxed=None, where="store") -> Pick:
    score, why, trade = _score(r, cond)
    if cond.get("diag_min") or cond.get("diag_max"):
        why.insert(0, f"{r.diagonal_in}″ — нужный размер")
    w = cond.get("width_max_cm")
    if w and r.width_cm <= w:
        why.insert(1, f"Ширина ≈{r.width_cm} см — помещается в {w} см (сверьте по карточке)")
        if not (cond.get("diag_min") or cond.get("diag_max")):  # размер не назван: лучше самый большой, что влезает
            score += 3 if r.width_cm >= 0.85 * w else (1 if r.width_cm >= 0.7 * w else 0)
    pm = cond.get("price_max")
    if pm:
        if r.price <= pm:
            why.append(f"В бюджете: {rub(r.price)}")
        else:
            diff = r.price - pm
            trade.insert(0, f"Дороже бюджета на {rub(diff)} (+{round(diff / pm * 100)}%)")
            score -= 2
    if relaxed:
        trade.insert(0, f"Ослаблено: {relaxed}")
    stock = int(r[store_col]) if where == "store" else int(r.stock_warehouse)
    return Pick(row=r, score=score, why=why[:4], trade=trade[:2], stock=stock, where=where, relaxed=relaxed)


def _diverse(picks: list[Pick], limit=5, per_brand=2) -> list[Pick]:
    out, cnt = [], {}
    for p in sorted(picks, key=lambda p: (-p.score, p.row.price)):
        b = p.row.brand
        if cnt.get(b, 0) >= per_brand:
            continue
        cnt[b] = cnt.get(b, 0) + 1
        out.append(p)
        if len(out) >= limit:
            break
    return out


BLOCKER_LABEL = {
    "diag": "размер экрана",
    "price": "бюджет",
    "resolution": "разрешение",
    "panel": "тип матрицы",
    "min_refresh": "частота обновления",
    "panel_not": "исключённая матрица",
    "price_min": "нижняя граница бюджета",
    "width_max_cm": "ширина ниши",
}


def recommend(cat: pd.DataFrame, cond: dict, store_col: str, limit: int = 5) -> Result:
    checks = _mandatory_checks(cond)
    pm = cond.get("price_max")
    in_store = cat[cat[store_col] > 0]

    exact, near_budget = [], []
    for _, r in in_store.iterrows():
        if not _passes(r, checks):
            continue
        if not pm or r.price <= pm:
            exact.append(_make_pick(r, cond, store_col))
        elif r.price <= pm * (1 + OVER_BUDGET_TOLERANCE):
            near_budget.append(_make_pick(r, cond, store_col))

    picks = _diverse(exact, limit)
    if len(picks) < 3 and near_budget:  # мало точных — добавляем «чуть дороже» с названным компромиссом
        picks += _diverse(near_budget, 3 - len(picks))

    # Склад: модели, которых нет в магазине, но они подходят
    wh = []
    for _, r in cat[(cat[store_col] == 0) & (cat.stock_warehouse > 0)].iterrows():
        if _passes(r, checks) and (not pm or r.price <= pm):
            wh.append(_make_pick(r, cond, store_col, where="warehouse"))
    res = Result(picks=picks, found_total=len(exact), warehouse=_diverse(wh, 2))

    if not picks:
        res.blocker, res.nearest = _explain_empty(in_store, cond, checks, store_col)
    return res


PANEL_RANK = {"OLED": 3, "Mini LED": 3, "QLED": 2, "LED": 0}


def _explain_empty(in_store, cond, checks, store_col):
    """Какое одно условие отсекает больше всего моделей — и что будет, если его ослабить.
    Ближайшие варианты сортируются по близости именно к ослабленному условию."""
    pm = cond.get("price_max")
    candidates = {}
    for key in list(checks) + (["price"] if pm else []):
        rows = []
        for _, r in in_store.iterrows():
            ok_other = _passes(r, checks, skip=key if key != "price" else None)
            ok_price = (not pm) or key == "price" or r.price <= pm
            if ok_other and ok_price:
                rows.append(r)
        candidates[key] = rows
    if not candidates:
        return None, []
    key = max(candidates, key=lambda k: len(candidates[k]))
    rows = candidates[key]
    label = BLOCKER_LABEL.get(key, key)
    if not rows:
        return label, []

    def relaxed_text(r):
        if key == "diag":
            lo, hi = cond.get("diag_min"), cond.get("diag_max")
            want = f"{lo}″" if lo == hi else f"{lo or '…'}–{hi or '…'}″"
            return f"размер {r.diagonal_in}″ вместо {want}"
        if key == "panel":
            return f"матрица {r.panel} вместо {cond['panel']}"
        if key == "resolution":
            return f"разрешение {r.resolution} вместо {cond['resolution']}"
        if key == "min_refresh":
            return f"{r.refresh_hz} Гц вместо {cond['min_refresh']} Гц"
        if key == "panel_not":
            return f"матрица {r.panel}, хотя её не хотели"
        if key == "price_min":
            return f"дешевле нижней границы {rub(cond['price_min'])}"
        if key == "width_max_cm":
            return f"ширина ≈{r.width_cm} см, а место до {cond['width_max_cm']} см"
        return None  # бюджет: компромисс «дороже на …» добавится сам

    picks = []
    for r in rows:
        p = _make_pick(r, cond, store_col, relaxed=relaxed_text(r))
        if key == "diag" and p.why and p.why[0].endswith("нужный размер"):
            p.why = p.why[1:]
        picks.append(p)
    if key == "diag":
        lo, hi = cond.get("diag_min") or 0, cond.get("diag_max") or 200
        target = (lo + hi) / 2
        picks.sort(key=lambda p: (abs(p.row.diagonal_in - target), -p.score, p.row.price))
    elif key == "panel":
        picks.sort(key=lambda p: (-PANEL_RANK[p.row.panel], -p.score, p.row.price))
    elif key == "price":
        picks.sort(key=lambda p: p.row.price)
    else:
        picks.sort(key=lambda p: (-p.score, p.row.price))
    return label, picks[:2]


def count_matches(cat: pd.DataFrame, cond: dict, store_col: str) -> int:
    checks = _mandatory_checks(cond)
    pm = cond.get("price_max")
    n = 0
    for _, r in cat[cat[store_col] > 0].iterrows():
        if _passes(r, checks) and (not pm or r.price <= pm):
            n += 1
    return n


# ---------- Сравнение ----------
COMPARE_ROWS = [
    ("Диагональ", "diagonal_in", lambda v: f"{v}″", "max"),
    ("Матрица", "panel", str, None),
    ("Разрешение", "resolution", str, None),
    ("Частота", "refresh_hz", lambda v: f"{v} Гц", "max"),
    ("HDMI 2.1", "hdmi21", lambda v: "есть" if v else "нет", "max"),
    ("Яркость", "brightness_nits", lambda v: f"{v} нит", "max"),
    ("Платформа", "smart_os", str, None),
    ("Ширина ≈", "width_cm", lambda v: f"{v} см", None),
    ("Цена", "price", rub, "min"),
]


def compare_table(rows: list[pd.Series], store_col: str) -> pd.DataFrame:
    data, best = {}, {}
    for label, col, fmt, better in COMPARE_ROWS:
        vals = [r[col] for r in rows]
        data[label] = [fmt(v) for v in vals]
        if better and len(set(vals)) > 1:
            target = max(vals) if better == "max" else min(vals)
            best[label] = [v == target for v in vals]
    data["Наличие"] = [f"{int(r[store_col])} шт." if r[store_col] > 0 else "склад" for r in rows]
    df = pd.DataFrame(data, index=[f"{r.brand} {r.model}" for r in rows]).T
    df.attrs["best"] = best
    return df


# ---------- Что ещё уточнить у клиента (этап «Потребности») ----------
def missing_questions(cond: dict, limit: int = 2) -> list[str]:
    """Ключи вопросов из QUESTIONS, на которые у клиента ещё нет ответа, — по важности для подбора."""
    has_size = any(cond.get(k) for k in ("diag_min", "diag_max", "width_max_cm"))
    out = []
    if not has_size:
        out.append("distance")
    if not cond.get("price_max"):
        out.append("budget")
    if not cond.get("use"):
        out.append("use")
    if not cond.get("room") and cond.get("use") != "games":  # для игр комната почти не влияет на выбор
        out.append("room")
    return out[:limit]


# ---------- Экран «Показать клиенту» ----------
def explain_pick(r, cond: dict, store_col: str) -> Pick:
    """Объяснение для одной модели теми же правилами, что и в подборке."""
    where = "store" if r[store_col] > 0 else "warehouse"
    return _make_pick(r, cond, store_col, where=where)


def client_facts(r) -> list[str]:
    """Три факта о модели простыми словами — без внутренних кодов и остатков."""
    d = int(r.diagonal_in)
    dist = "до 2 м" if d <= 50 else ("2–3 м" if d <= 65 else "больше 3 м")
    picture = {"OLED": "OLED — глубокий чёрный и сочные цвета", "Mini LED": "Mini LED — очень ярко и контрастно",
               "QLED": "QLED — насыщенные цвета", "LED": "LED — обычная матрица"}.get(r.panel, r.panel)
    smooth = (f"{r.refresh_hz} Гц — плавно в играх и спорте" if r.refresh_hz >= 100
              else f"{r.refresh_hz} Гц — для фильмов и ТВ достаточно")
    apps = ("Своя система — базовые приложения" if r.smart_os == "Своя ОС"
            else f"{r.smart_os} — YouTube и онлайн-кинотеатры")
    return [f"Экран {d}″ — удобно смотреть с {dist}", f"{picture}, {r.resolution}", smooth, apps]


def client_diff(rows: list) -> list[str]:
    """Чем модели отличаются друг от друга — для разговора с клиентом."""
    if len(rows) < 2:
        return []
    name = lambda r: f"{r.brand} {r.model}"
    out = []
    by_price = sorted(rows, key=lambda r: r.price)
    gap = by_price[1].price - by_price[0].price
    if gap > 0:
        out.append(f"{name(by_price[0])} дешевле на {rub(gap)}")
    for col, text, unit in (("diagonal_in", "экран больше", "″"), ("refresh_hz", "картинка плавнее", " Гц"),
                            ("brightness_nits", "ярче — лучше видно днём", " нит")):
        vals = [int(r[col]) for r in rows]
        top = max(vals)
        if len(set(vals)) > 1 and vals.count(top) == 1:
            r = rows[vals.index(top)]
            out.append(f"У {name(r)} {text}: {top}{unit}")
    best_panel = max(rows, key=lambda r: PANEL_RANK.get(r.panel, 0))
    if len({r.panel for r in rows}) > 1 and PANEL_RANK.get(best_panel.panel, 0) >= 2:
        out.append(f"У {name(best_panel)} матрица {best_panel.panel} — контраст и цвета в кино лучше")
    hdmi = [r for r in rows if r.hdmi21]
    if 0 < len(hdmi) < len(rows):
        out.append("HDMI 2.1 для консоли — только у " + ", ".join(name(r) for r in hdmi))
    return out
