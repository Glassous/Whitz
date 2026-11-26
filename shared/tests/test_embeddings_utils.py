import math

import pytest

from whitz_rag.embeddings import (
    char_trigrams,
    escape_like,
    fit_embedding,
    jaccard_sim,
    vector_literal,
)


def test_fit_embedding_pads_and_normalizes():
    out = fit_embedding([3.0, 4.0], dim=4)
    assert len(out) == 4
    assert out[:2] == pytest.approx([0.6, 0.8])
    assert out[2:] == [0.0, 0.0]


def test_fit_embedding_truncates():
    out = fit_embedding([1.0] * 10, dim=4)
    assert len(out) == 4
    assert math.isclose(sum(v * v for v in out), 1.0)


def test_fit_embedding_zero_vector_and_invalid_dim():
    assert fit_embedding([0.0, 0.0], dim=3) == [0.0, 0.0, 0.0]
    with pytest.raises(ValueError):
        fit_embedding([1.0], dim=0)


def test_vector_literal():
    assert vector_literal([1, 0.5]) == "[1.00000000,0.50000000]"
    assert vector_literal([]) == "[]"


def test_escape_like():
    assert escape_like("50%_off\\") == "50\\%\\_off\\\\"


def test_char_trigrams():
    assert char_trigrams("") == set()
    assert char_trigrams("ab") == {"ab"}
    assert char_trigrams("abcd") == {"abc", "bcd"}
    assert char_trigrams("ABC") == char_trigrams("abc")


def test_jaccard_sim():
    assert jaccard_sim(set(), {"a"}) == 0.0
    assert jaccard_sim({"a"}, {"b"}) == 0.0
    assert jaccard_sim({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard_sim({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)
