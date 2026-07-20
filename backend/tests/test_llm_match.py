from services.llm_match import _extract_json, _normalize


def test_extract_json_handles_noise_and_code_fences():
    text = """前置说明
```json
{"score": 88, "matched_points": ["学科匹配"], "gaps": [], "reason": "ok", "cover_letter": "hello"}
```
后置说明"""
    data = _extract_json(text)
    assert data["score"] == 88
    assert data["matched_points"] == ["学科匹配"]


def test_normalize_clamps_score_bounds():
    high = _normalize({"score": 999, "matched_points": [], "gaps": [], "reason": "x", "cover_letter": "y"})
    low = _normalize({"score": -5, "matched_points": [], "gaps": [], "reason": "x", "cover_letter": "y"})

    assert high["score"] == 100
    assert low["score"] == 0
