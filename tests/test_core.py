import json

import pytest

from core.catalog import load_catalog
from core.parser import extract_json, normalize, parse, parse_rules, validate_llm_items
from core.rules import compare_table, count_matches, recommend

CAT = load_catalog()
STORE = "stock_store1"


def kv(items):
    return {i["k"]: i["v"] for i in items}


# ---------- Нормализация и разбор правилами ----------
@pytest.mark.parametrize("text,expected", [
    ("шестьдесят пять дюймов", "65 дюймов"),
    ("до ста пятидесяти тысяч", "до 150 тысяч"),
    ("диван в двух с половиной метрах", "диван в 2.5 метрах"),
    ("до 40 000 рублей", "до 40000 рублей"),
])
def test_normalize(text, expected):
    assert normalize(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("65 дюймов для PS5, до 100 тысяч", {"diag_exact": 65, "use": "games", "price_max": 100000}),
    ("шестьдесят пять дюймов для плейстейшн до ста тысяч", {"diag_exact": 65, "use": "games", "price_max": 100000}),
    ("комната солнечная, смотрят сериалы, с Алисой", {"room": "bright", "use": "movies", "smart_os": "Яндекс ТВ"}),
    ("диван в трёх метрах, олед, бюджет 150", {"distance_m": 3.0, "panel": "OLED", "price_max": 150000}),
    ('телевизор 55" QLED 120 Гц', {"diag_exact": 55, "panel": "QLED", "min_refresh": 120}),
    ("до 3 метров до дивана, для ютуба", {"distance_m": 3.0, "use": "tv"}),
    ("для бабушки на дачу, до двадцати пяти тысяч", {"use": "tv", "price_max": 25000}),
])
def test_parse_rules(text, expected):
    assert kv(parse_rules(text)) == expected


def test_distance_not_taken_as_price():
    assert "price_max" not in kv(parse_rules("до 3 метров"))


# ---------- Проверка ответа модели ----------
def test_llm_validation_rejects_invented_condition():
    text = "65 дюймов для PS5"
    data = {"c": [
        {"k": "diag_exact", "v": 65, "q": "65 дюймов"},
        {"k": "use", "v": "games", "q": "для PS5"},
        {"k": "price_max", "v": 80000, "q": "до 80 тысяч"},  # выдумано: такого во фразе нет
        {"k": "brand", "v": "X", "q": "65"},                 # недопустимый ключ
    ]}
    acc, rej = validate_llm_items(text, data, parse_rules(text))
    assert kv(acc) == {"diag_exact": 65, "use": "games"}
    assert {r["k"] for r in rej} == {"price_max", "brand"}


def test_llm_price_in_thousands_is_normalized():
    acc, _ = validate_llm_items("бюджет 60", {"c": [{"k": "price_max", "v": 60, "q": "бюджет 60"}]}, [])
    assert kv(acc) == {"price_max": 60000}


def test_extract_json_with_noise():
    raw = 'Вот ответ: {"c":[{"k":"use","v":"games","q":"игры"}]} готово'
    assert extract_json(raw) == {"c": [{"k": "use", "v": "games", "q": "игры"}]}
    assert extract_json("нет json") is None


class FakeLLM:
    model_id = "fake"

    def __init__(self, out):
        self.out = out

    def __call__(self, text):
        return self.out


def test_parse_merges_llm_and_rules():
    # модель нашла только диагональ, правила добирают бюджет и назначение
    llm = FakeLLM(json.dumps({"c": [{"k": "diag_exact", "v": 65, "q": "65 дюймов"}]}))
    res = parse("65 дюймов для PS5 до 100 тысяч", llm)
    assert res.cond == {"diag_min": 65, "diag_max": 65, "use": "games", "price_max": 100000}
    assert {i["source"] for i in res.accepted} == {"модель", "правила"}


def test_parse_survives_broken_llm():
    res = parse("олед до 150 тысяч", FakeLLM("не понимаю"))
    assert res.error and res.cond == {"panel": "OLED", "price_max": 150000}


def test_parse_survives_llm_exception():
    def boom(_):
        raise RuntimeError("cuda oom")
    res = parse("олед", boom)
    assert "ошибка модели" in res.error and res.cond == {"panel": "OLED"}


# ---------- Подбор ----------
def test_recommend_respects_mandatory_and_stock():
    cond = {"diag_min": 55, "diag_max": 65, "price_max": 100000, "use": "games"}
    res = recommend(CAT, cond, STORE)
    assert 1 <= len(res.picks) <= 5
    for p in res.picks:
        r = p.row
        assert 55 <= r.diagonal_in <= 65
        assert r[STORE] > 0
        assert r.price <= 100000 * 1.10
    brands = [p.row.brand for p in res.picks]
    assert all(brands.count(b) <= 2 for b in brands)


def test_games_prefers_hdmi21():
    res = recommend(CAT, {"use": "games", "diag_min": 50, "diag_max": 65}, STORE)
    assert res.picks[0].row.hdmi21 == 1


def test_over_budget_named_as_compromise():
    # бюджет, при котором точных совпадений мало
    cond = {"diag_min": 65, "diag_max": 65, "price_max": 60000}
    res = recommend(CAT, cond, STORE)
    for p in res.picks:
        if p.row.price > 60000:
            assert any("Дороже бюджета" in t for t in p.trade)


def test_empty_result_explains_blocker():
    cond = {"diag_min": 85, "diag_max": 85, "price_max": 40000}
    res = recommend(CAT, cond, STORE)
    assert res.picks == []
    assert res.blocker in {"размер экрана", "бюджет"}


def test_count_matches_consistent():
    cond = {"diag_min": 43, "diag_max": 50}
    n = count_matches(CAT, cond, STORE)
    expected = len(CAT[(CAT[STORE] > 0) & CAT.diagonal_in.between(43, 50)])
    assert n == expected


def test_compare_table_highlights():
    rows = [r for _, r in CAT.iloc[[12, 13, 14]].iterrows()]
    df = compare_table(rows, STORE)
    assert "Цена" in df.index and "Частота" in df.attrs["best"]


def _wav(seconds, rate=16000):
    import io, wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


def test_trim_wav():
    import io, wave
    from core.asr import _trim_wav
    data, dur = _trim_wav(_wav(30), 24)
    assert round(dur) == 30
    with wave.open(io.BytesIO(data)) as w:
        assert abs(w.getnframes() / w.getframerate() - 24) < 0.01
    data2, dur2 = _trim_wav(_wav(5), 24)
    assert round(dur2) == 5 and data2 == _wav(5)


def test_asr_transcribe_with_fake_model():
    from core.asr import ASR
    asr = ASR.__new__(ASR)
    asr.kind, asr.note = "GigaAM-v3 (fake)", ""

    class R:
        text = "65 дюймов для PS5"
    asr.model = type("M", (), {"transcribe": lambda self, path: R()})()
    out = asr.transcribe(_wav(2))
    assert out["text"] == "65 дюймов для PS5" and out["seconds"] == 2.0


# ---------- Категории и частые запросы ----------
from core.categories import CATEGORIES  # noqa: E402
from core.rules import cond_labels  # noqa: E402


def test_only_tv_ready_and_all_have_preview():
    assert [c.id for c in CATEGORIES.values() if c.ready] == ["tv"]
    for c in CATEGORIES.values():
        assert len(c.questions) >= 3 and c.voice_example and len(c.compare) >= 4


@pytest.mark.parametrize("label", list(CATEGORIES["tv"].presets))
def test_tv_presets_give_known_conditions_and_picks(label):
    cond = dict(CATEGORIES["tv"].presets[label])
    known = {"use", "room", "diag_min", "diag_max", "price_max", "panel", "resolution", "min_refresh", "smart_os"}
    assert set(cond) <= known
    assert cond_labels(cond)  # у каждого условия есть подпись-чип
    res = recommend(CAT, cond, "stock_store1")
    assert res.picks or res.nearest  # частый запрос не должен давать пустой экран
