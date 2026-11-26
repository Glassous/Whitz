from whitz_rag.tokenizer import estimate_tokens, expand_cjk_bigrams


def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0


def test_estimate_tokens_minimum_one():
    assert estimate_tokens("a") == 1


def test_estimate_tokens_cjk_heavier_than_latin():
    assert estimate_tokens("你好世界" * 10) > estimate_tokens("abcd" * 10)


def test_estimate_tokens_exact_values():
    # 0.28 / 0.72 per char with ceil; tolerate float rounding of one token
    assert 28 <= estimate_tokens("a" * 100) <= 29
    assert 72 <= estimate_tokens("中" * 100) <= 73


def test_bigrams_empty_and_no_cjk():
    assert expand_cjk_bigrams("") == ""
    assert expand_cjk_bigrams("hello world") == "hello world"
    assert expand_cjk_bigrams("单") == "单"


def test_bigrams_appended_and_deduplicated():
    out = expand_cjk_bigrams("你好你好")
    head, tail = out.split("\n")
    assert head == "你好你好"
    assert tail.split() == ["你好", "好你"]


def test_bigrams_max_limit():
    out = expand_cjk_bigrams("一二三四五六七八", max_bigrams=3)
    assert len(out.split("\n")[1].split()) == 3
