"""Разбор выжимки продавца в условия подбора.

Схема: малая языковая модель извлекает условия в JSON -> каждое условие проверяется
(допустимый ключ, допустимое значение, цитата из исходной фразы) -> недостающее
добирают правила (регулярные выражения). Если модель недоступна, работают только правила.
Модель не выбирает товар и не придумывает характеристики: она только переводит слова в условия.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

# ---------- Нормализация текста и числа словами ----------
_NUM_WORDS = {
    "ноль": 0, "один": 1, "одна": 1, "одного": 1, "два": 2, "две": 2, "двух": 2, "три": 3, "трех": 3,
    "четыре": 4, "четырех": 4, "пять": 5, "пяти": 5, "шесть": 6, "шести": 6, "семь": 7, "семи": 7,
    "восемь": 8, "восьми": 8, "девять": 9, "девяти": 9, "десять": 10, "десяти": 10,
    "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15,
    "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19,
    "двадцать": 20, "двадцати": 20, "тридцать": 30, "тридцати": 30, "сорок": 40, "сорока": 40,
    "пятьдесят": 50, "пятидесяти": 50, "шестьдесят": 60, "шестидесяти": 60,
    "семьдесят": 70, "семидесяти": 70, "восемьдесят": 80, "восьмидесяти": 80,
    "девяносто": 90, "девяноста": 90, "сто": 100, "ста": 100, "двести": 200, "двухсот": 200,
    "триста": 300, "трехсот": 300, "четыреста": 400, "пятьсот": 500,
}


def _words_to_digits(text: str) -> str:
    tokens = text.split()
    out, acc, last = [], None, None
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in ("полтора", "полторы"):
            out.append("1.5")
            i += 1
            continue
        if t in _NUM_WORDS:
            v = _NUM_WORDS[t]
            if acc is not None and last is not None and v < last and len(str(v)) < len(str(last)):
                acc += v
            else:
                if acc is not None:
                    out.append(str(acc))
                acc = v
            last = v
            # «два с половиной»
            if i + 2 < len(tokens) and tokens[i + 1] == "с" and tokens[i + 2] == "половиной":
                out.append(f"{acc}.5")
                acc, last = None, None
                i += 3
                continue
            i += 1
            continue
        if acc is not None:
            out.append(str(acc))
            acc, last = None, None
        out.append(t)
        i += 1
    if acc is not None:
        out.append(str(acc))
    return " ".join(out)


def normalize(text: str) -> str:
    t = text.lower().replace("ё", "е")
    t = re.sub(r"(\d)\s*(?:\"|″|”)", r"\1 дюйм", t)  # 55" -> 55 дюйм
    t = re.sub(r"[«»\"“”„,!?;:()]", " ", t)
    t = re.sub(r"(\d)\s+(\d{3})\b", r"\1\2", t)  # «40 000» -> «40000»
    t = re.sub(r"\s+", " ", t).strip()
    return _words_to_digits(t)


# ---------- Допустимые условия ----------
ENUMS = {
    "use": {"movies": "movies", "кино": "movies", "games": "games", "игры": "games", "tv": "tv", "тв": "tv"},
    "room": {"bright": "bright", "светлая": "bright", "dark": "dark", "темная": "dark"},
    "panel": {"oled": "OLED", "qled": "QLED", "mini led": "Mini LED", "miniled": "Mini LED", "led": "LED"},
    "resolution": {"4k": "4K", "uhd": "4K", "full hd": "Full HD", "fullhd": "Full HD", "1080p": "Full HD"},
    "smart_os": {"яндекс тв": "Яндекс ТВ", "яндекс": "Яндекс ТВ", "google tv": "Google TV", "google": "Google TV",
                 "android tv": "Google TV"},
}
ALLOWED = ["diag_exact", "distance_m", "price_max", "use", "room", "panel", "resolution", "min_refresh", "smart_os"]
KEY_LABEL = {
    "diag_exact": "диагональ", "distance_m": "расстояние до дивана", "price_max": "бюджет", "use": "назначение",
    "room": "комната", "panel": "матрица", "resolution": "разрешение", "min_refresh": "частота", "smart_os": "платформа",
}


def _clean_value(k: str, v):
    """Приводит значение к допустимому виду или возвращает None."""
    try:
        if k == "diag_exact":
            v = int(float(v))
            return v if 24 <= v <= 100 else None
        if k == "distance_m":
            v = float(str(v).replace(",", "."))
            return v if 0.5 <= v <= 8 else None
        if k == "price_max":
            v = float(str(v).replace(" ", "").replace(",", "."))
            if v < 1000:
                v *= 1000  # «до 40» в контексте цены — это тысячи
            v = int(v)
            return v if 5000 <= v <= 1_000_000 else None
        if k == "min_refresh":
            v = int(float(v))
            return 120 if v >= 120 else (100 if v >= 100 else None)
        if k in ENUMS:
            return ENUMS[k].get(str(v).strip().lower())
    except (TypeError, ValueError):
        return None
    return None


# ---------- Разбор правилами ----------
def _distance_to_diag(d: float) -> tuple[int, int]:
    if d <= 2.0:
        return (32, 50)
    if d <= 3.0:
        return (55, 65)
    return (65, 85)


def parse_rules(text: str) -> list[dict]:
    t = normalize(text)
    items: list[dict] = []

    def add(k, v, m):
        if v is not None and all(i["k"] != k for i in items):
            items.append({"k": k, "v": v, "q": m.group(0).strip() if hasattr(m, "group") else m})

    m = re.search(r"(\d{2,3})\s*(?:-?\s*ти\s*)?(?:дюйм\w*|″|''|инч\w*|inch\w*)", t) or \
        re.search(r"диагонал\w*\s*(\d{2,3})", t)
    if m:
        add("diag_exact", _clean_value("diag_exact", m.group(1)), m)
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:м\b|метр\w*)", t)
    if m:
        add("distance_m", _clean_value("distance_m", m.group(1)), m)
    m = re.search(r"(?:до|за|не дороже|в пределах|максимум|бюджет\w*|около|примерно|тысяч на)\s*"
                  r"(\d+(?:[.,]\d+)?)(?![\d.,])(?!\s*(?:м\b|метр|дюйм|гц|герц|″))\s*(тыс\w*|т\.?\s?р\.?|к\b|руб\w*|₽)?", t)
    if m:
        add("price_max", _clean_value("price_max", m.group(1)), m)
    else:
        m = re.search(r"(\d{4,7})\s*(?:₽|руб\w*)", t)
        if m:
            add("price_max", _clean_value("price_max", m.group(1)), m)

    use_patterns = [
        ("games", r"игр\w*|ps\s?5|ps\s?4|playstation|плейстейшн\w*|плойк\w*|xbox|иксбокс\w*|приставк\w*|консол\w*"),
        ("movies", r"кино\w*|фильм\w*|сериал\w*|кинопоиск|нетфликс"),
        ("tv", r"ютуб\w*|youtube|новост\w*|телевидени\w*|каналы|на дачу|для бабушк\w*|фоном"),
    ]
    for val, pat in use_patterns:
        m = re.search(pat, t)
        if m:
            add("use", val, m)
            break
    m = re.search(r"светл\w*|солнечн\w*|окн[оа]\w*", t)
    if m:
        add("room", "bright", m)
    else:
        m = re.search(r"темн\w*|затемн\w*", t)
        if m:
            add("room", "dark", m)
    for val, pat in [("Mini LED", r"mini\s?led|мини\s?лед\w*"), ("QLED", r"qled|кьюлед\w*|ку\s?лед"),
                     ("OLED", r"\boled|олед\w*")]:
        m = re.search(pat, t)
        if m:
            add("panel", val, m)
            break
    m = re.search(r"\b4\s?(?:k|к)\b|uhd|ultra\s?hd|ультра\s?эйч\s?ди", t)
    if m:
        add("resolution", "4K", m)
    else:
        m = re.search(r"full\s?hd|фулл?\s?(?:хд|эйч\s?ди)|1080", t)
        if m:
            add("resolution", "Full HD", m)
    m = re.search(r"(\d{3})\s*(?:гц|герц\w*|hz)", t)
    if m:
        add("min_refresh", _clean_value("min_refresh", m.group(1)), m)
    m = re.search(r"алис\w*|яндекс\w*", t)
    if m:
        add("smart_os", "Яндекс ТВ", m)
    else:
        m = re.search(r"google|гугл\w*|андроид\w*|android", t)
        if m:
            add("smart_os", "Google TV", m)
    return items


# ---------- Разбор малой моделью ----------
SYSTEM_PROMPT = """Ты извлекаешь условия подбора телевизора из короткой фразы продавца.
Верни ТОЛЬКО JSON вида {"c":[{"k":ключ,"v":значение,"q":"цитата из фразы"}]}.
Допустимые ключи и значения:
- diag_exact: диагональ в дюймах, целое число
- distance_m: расстояние до дивана в метрах, число
- price_max: максимальная цена в рублях, целое число
- use: "movies" (кино, сериалы) | "games" (игры, PS5, Xbox) | "tv" (телевидение, YouTube)
- room: "bright" (светлая, солнечная) | "dark" (тёмная)
- panel: "OLED" | "QLED" | "Mini LED" | "LED"
- resolution: "4K" | "Full HD"
- min_refresh: частота в Гц, целое число
- smart_os: "Яндекс ТВ" | "Google TV"
Правила: q — дословный кусок исходной фразы. Не добавляй условий, которых нет во фразе. Если условий нет — {"c":[]}."""

FEW_SHOT = [
    ("65 дюймов для PS5, до 100 тысяч",
     '{"c":[{"k":"diag_exact","v":65,"q":"65 дюймов"},{"k":"use","v":"games","q":"для PS5"},'
     '{"k":"price_max","v":100000,"q":"до 100 тысяч"}]}'),
    ("комната солнечная, смотрят сериалы, хотят с Алисой",
     '{"c":[{"k":"room","v":"bright","q":"комната солнечная"},{"k":"use","v":"movies","q":"смотрят сериалы"},'
     '{"k":"smart_os","v":"Яндекс ТВ","q":"с Алисой"}]}'),
    ("диван в трёх метрах, олед, бюджет 150",
     '{"c":[{"k":"distance_m","v":3,"q":"в трёх метрах"},{"k":"panel","v":"OLED","q":"олед"},'
     '{"k":"price_max","v":150000,"q":"бюджет 150"}]}'),
]


class LLMParser:
    def __init__(self, model_id: str, max_new_tokens: int = 160):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.tok = AutoTokenizer.from_pretrained(model_id)
        dtype = torch.float16 if self.device == "cuda" else torch.float32
        try:  # в новых transformers параметр называется dtype, в старых — torch_dtype
            self.model = AutoModelForCausalLM.from_pretrained(model_id, dtype=dtype)
        except TypeError:
            self.model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=dtype)
        self.model.to(self.device)
        self.model.eval()
        self.model_id = model_id
        self.max_new_tokens = max_new_tokens

    def __call__(self, text: str) -> str:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        for u, a in FEW_SHOT:
            msgs += [{"role": "user", "content": u}, {"role": "assistant", "content": a}]
        msgs.append({"role": "user", "content": text})
        prompt = self.tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        ids = self.tok(prompt, return_tensors="pt").to(self.device)
        with self.torch.inference_mode():
            out = self.model.generate(**ids, max_new_tokens=self.max_new_tokens, do_sample=False,
                                      pad_token_id=self.tok.eos_token_id)
        return self.tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)


def extract_json(raw: str):
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                chunk = raw[start:i + 1]
                for candidate in (chunk, chunk.replace("'", '"')):
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        continue
                return None
    return None


# ---------- Проверка и слияние ----------
@dataclass
class ParseResult:
    text: str
    cond: dict
    accepted: list[dict] = field(default_factory=list)   # {k, v, q, source}
    rejected: list[dict] = field(default_factory=list)   # {k, v, q, reason}
    raw_llm: str | None = None
    llm_ms: int | None = None
    error: str | None = None


def validate_llm_items(text: str, data, rules_items: list[dict]) -> tuple[list[dict], list[dict]]:
    norm_text = normalize(text)
    by_key_rules = {i["k"]: i for i in rules_items}
    accepted, rejected = [], []
    items = data.get("c", []) if isinstance(data, dict) else []
    for it in items:
        if not isinstance(it, dict):
            continue
        k, v, q = it.get("k"), it.get("v"), str(it.get("q") or "")
        if k not in ALLOWED:
            rejected.append({"k": k, "v": v, "q": q, "reason": "недопустимое условие"})
            continue
        if any(a["k"] == k for a in accepted):
            continue
        cv = _clean_value(k, v)
        if cv is None:
            rejected.append({"k": k, "v": v, "q": q, "reason": "недопустимое значение"})
            continue
        nq = normalize(q)
        quote_ok = bool(nq) and nq in norm_text
        rules_agree = k in by_key_rules and by_key_rules[k]["v"] == cv
        if quote_ok or rules_agree:
            accepted.append({"k": k, "v": cv, "q": q, "source": "модель"})
        else:
            rejected.append({"k": k, "v": v, "q": q, "reason": "нет такой цитаты во фразе"})
    return accepted, rejected


def items_to_cond(items: list[dict]) -> dict:
    cond = {}
    d = {i["k"]: i["v"] for i in items}
    if "diag_exact" in d:
        cond["diag_min"] = cond["diag_max"] = d["diag_exact"]
    elif "distance_m" in d:
        cond["diag_min"], cond["diag_max"] = _distance_to_diag(d["distance_m"])
    for k in ("price_max", "use", "room", "panel", "resolution", "min_refresh", "smart_os"):
        if k in d:
            cond[k] = d[k]
    return cond


def parse(text: str, llm: LLMParser | None) -> ParseResult:
    rules_items = parse_rules(text)
    res = ParseResult(text=text, cond={})
    accepted: list[dict] = []
    if llm is not None:
        t0 = time.perf_counter()
        try:
            res.raw_llm = llm(text)
            data = extract_json(res.raw_llm)
            if data is None:
                res.error = "модель вернула не JSON — использованы правила"
            else:
                accepted, res.rejected = validate_llm_items(text, data, rules_items)
        except Exception as e:  # модель не должна ломать консультацию
            res.error = f"ошибка модели: {e} — использованы правила"
        res.llm_ms = int((time.perf_counter() - t0) * 1000)
    have = {a["k"] for a in accepted}
    for r in rules_items:  # правила добирают то, что модель пропустила
        if r["k"] not in have:
            accepted.append({**r, "source": "правила"})
    res.accepted = accepted
    res.cond = items_to_cond(accepted)
    return res
