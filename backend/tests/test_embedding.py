import math

from config import settings
from services.embedding import embed


def test_stub_embedding_returns_configured_normalized_vector():
    vector = embed(["深圳小学语文教师招聘"])[0]

    assert len(vector) == settings.EMBEDDING_DIM
    assert any(value != 0 for value in vector)
    norm = math.sqrt(sum(value * value for value in vector))
    assert 0.99 <= norm <= 1.01
