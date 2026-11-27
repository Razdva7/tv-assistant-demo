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


# ---------- Новые условия (после проверки 26.11.2026) ----------
def test_negation_excludes_panel():
    res = recommend(CAT, {"panel_not": "OLED"}, STORE)
    assert res.picks and all(p.row.panel != "OLED" for p in res.picks)


def test_price_range_filters_both_sides():
    res = recommend(CAT, {"price_min": 50000, "price_max": 80000}, STORE)
    assert res.picks and all(50000 <= p.row.price <= 80000 for p in res.picks)


def test_width_prefers_largest_that_fits():
    res = recommend(CAT, {"width_max_cm": 125}, STORE)
    assert res.picks and all(p.row.width_cm <= 125 for p in res.picks)
    assert res.picks[0].row.diagonal_in >= 50


def test_sport_prefers_high_refresh():
    res = recommend(CAT, {"use": "sport"}, STORE)
    assert res.picks[0].row.refresh_hz >= 100


def test_llm_cannot_flip_negation():
    data = {"c": [{"k": "panel", "v": "OLED", "q": "OLED"}]}
    rules_items = parse_rules("только не OLED")
    acc, rej = validate_llm_items("только не OLED", data, rules_items)
    assert not acc and rej[0]["reason"] == "во фразе отрицание"


def test_llm_new_keys_accepted():
    text = "55 или 65 дюймов, повесят на стену"
    data = {"c": [{"k": "diag_min", "v": 55, "q": "55 или 65 дюймов"}, {"k": "diag_max", "v": 65, "q": "55 или 65 дюймов"},
                  {"k": "wall_mount", "v": True, "q": "повесят на стену"}]}
    acc, _ = validate_llm_items(text, data, parse_rules(text))
    assert kv(acc) == {"diag_min": 55, "diag_max": 65, "wall_mount": True}


def test_knowledge_addons_only_on_need():
    from core import knowledge
    assert knowledge.addons("tv", {}) == []
    items = [a["item"] for a in knowledge.addons("tv", {"wall_mount": True, "use": "games"})]
    assert any("Кронштейн" in i for i in items) and any("HDMI" in i for i in items)
    assert any("Доставка" in a["item"] for a in knowledge.addons("tv", {"diag_min": 65, "diag_max": 75}))
    assert not any("Доставка" in a["item"] for a in knowledge.addons("tv", {"diag_min": 55, "diag_max": 55}))


def test_knowledge_tables_load_and_summary():
    from core import knowledge
    assert len(knowledge.objections("tv")) >= 5 and len(knowledge.terms("tv")) >= 5
    s = knowledge.summary({"diag_min": 55, "diag_max": 65, "panel_not": "OLED"})
    assert s.startswith("Правильно понимаю") and "не OLED" in s


# ---------- Версия для показа: «Уточните у клиента», экран клиента, итоги ----------
from core.report import summarize
from core.rules import client_diff, client_facts, explain_pick, missing_questions


def test_missing_questions_order_and_limit():
    assert missing_questions({}) == ["distance", "budget"]
    assert missing_questions({"diag_min": 55, "diag_max": 65}) == ["budget", "use"]
    assert missing_questions({"width_max_cm": 120, "price_max": 50000}) == ["use", "room"]
    # для игр комнату не спрашиваем; всё известно — вопросов нет
    assert missing_questions({"diag_min": 65, "diag_max": 65, "price_max": 1, "use": "games"}) == []


def test_client_view_has_no_internal_details():
    cat = load_catalog()
    rows = [cat.iloc[i] for i in (10, 20, 25)]
    for r in rows:
        facts = client_facts(r)
        assert len(facts) == 4 and str(r.diagonal_in) in facts[0]
        assert not any("шт." in f or "stock" in f for f in facts)
        p = explain_pick(r, {"use": "games"}, "stock_store1")
        assert p.where in ("store", "warehouse")
    diff = client_diff(rows)
    assert diff and any("дешевле" in d for d in diff)
    assert client_diff(rows[:1]) == []


def test_client_diff_names_only_true_differences():
    cat = load_catalog()
    r = cat.iloc[5]
    assert client_diff([r, r.copy()]) == []  # одинаковые модели — отличий нет


def test_report_counts_unmet_demand():
    import json
    import pandas as pd

    rows = [
        ("shown", {"use": "games"}, ""),
        ("no_match", {"diag_min": 65, "diag_max": 65, "panel": "OLED", "price_max": 90000}, ""),
        ("no_match", {"diag_min": 65, "diag_max": 65, "panel": "OLED", "price_max": 90000}, ""),
        ("wrong", {}, "не та цена"),
    ]
    log = pd.DataFrame([{"outcome": o, "conditions": json.dumps(c, ensure_ascii=False), "reason": r or None,
                         "terms_done": 4, "terms_total": 8} for o, c, r in rows])
    rep = summarize(log)
    assert rep["total"] == 4 and rep["shown_share"] == 25 and rep["no_match"] == 2
    assert rep["unmet"][0][1] == 2 and "OLED" in rep["unmet"][0][0]
    assert rep["wrong_reasons"] == [("не та цена", 1)]
    assert rep["terms_avg"] == 4.0
    assert summarize(log.iloc[0:0])["total"] == 0


# ---------- Диалог: одно окно «что делать сейчас» ----------
from core import knowledge
from core.dialog import build_reply, merge_cond, summary_text


def test_reply_one_window_is_short():
    r = build_reply(CAT, {"diag_min": 55, "diag_max": 65, "panel_not": "OLED"}, STORE)
    assert r.understood.startswith("телевизор — ") and "не OLED" in r.understood
    assert r.action.startswith("Покажите **") and "₽" not in r.action  # цена только в карточке
    assert len(r.reasons) <= 3 and len(r.alts) <= 2 and len(r.asks) <= 2
    assert all("OLED" != p.row.panel for p in r.picks)
    assert r.asks == ["budget", "use"]


def test_reply_empty_and_no_match():
    r = build_reply(CAT, {}, STORE)
    assert "Спросите" in r.action and r.asks == ["distance", "budget"]
    r = build_reply(CAT, {"diag_min": 65, "diag_max": 65, "panel": "OLED", "price_max": 90000}, STORE)
    assert not r.exact and "мешает" in r.action
    assert any(x.startswith("Компромисс") for x in r.reasons)


def test_reply_skips_answered_questions_and_offers_addons_by_need():
    r = build_reply(CAT, {"diag_min": 55, "diag_max": 55}, STORE, skip_asks={"budget"})
    assert "budget" not in r.asks
    r = build_reply(CAT, {"diag_min": 65, "diag_max": 65, "wall_mount": True}, STORE)
    assert any("Кронштейн" in a["item"] for a in r.addons)
    assert build_reply(CAT, {"diag_min": 43, "diag_max": 43}, STORE).addons == []


def test_merge_cond_replaces_opposites():
    assert merge_cond({"panel_not": "OLED"}, {"panel": "OLED"}) == {"panel": "OLED"}
    assert merge_cond({"panel": "OLED"}, {"panel_not": "OLED"}) == {"panel_not": "OLED"}
    assert merge_cond({"price_min": 80000}, {"price_max": 50000}) == {"price_max": 50000}
    assert merge_cond({"use": "games"}, {"price_max": 1}) == {"use": "games", "price_max": 1}


@pytest.mark.parametrize("text,question,expected", [
    ("OLED выгорает?", True, "OLED выгорает?"),
    ("а он не выгорит", False, "OLED выгорает?"),
    ("дорого", False, "Почему этот дороже, если диагональ та же?"),
    ("может подождать черную пятницу", True, "Может подождать скидок?"),
    ("зачем 120 герц", True, "Зачем 120 Гц, если смотрю кино?"),
])
def test_objection_matching(text, question, expected):
    o = knowledge.match_objection("tv", text)
    assert o and o["question"] == expected
    assert knowledge.is_question(text) == question


def test_condition_phrases_are_not_objections():
    for t in ["65 дюймов для PS5 до 100 тысяч", "только не олед, 55 или 65 дюймов", "повесят на стену"]:
        assert knowledge.match_objection("tv", t) is None


def test_summary_text_names_need_and_top_model():
    cond = {"use": "games", "diag_min": 65, "diag_max": 65}
    s = summary_text(cond, build_reply(CAT, cond, STORE))
    assert s.startswith("Правильно понимаю: нужен телевизор — ") and "советую" in s and "₽" in s
