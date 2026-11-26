import uuid

from app.services.file_provenance import extract_inline_file_ids, format_qa_snippet

A = "123e4567-e89b-12d3-a456-426614174000"
B = "223e4567-e89b-12d3-a456-426614174000"


def test_extract_inline_file_ids_dedup_and_order():
    text = f"x [[file:{A}|a.txt]] y [[file:{B}|b.txt]] [[file:{A}|a.txt]]"
    assert extract_inline_file_ids(text) == [uuid.UUID(A), uuid.UUID(B)]


def test_extract_inline_file_ids_empty_and_invalid():
    assert extract_inline_file_ids(None) == []
    assert extract_inline_file_ids("") == []
    assert extract_inline_file_ids("[[file:not-a-uuid|a]]") == []
    # 36 chars of valid charset but not a UUID
    assert extract_inline_file_ids("[[file:" + "-" * 36 + "|a]]") == []


def test_format_qa_snippet_basics():
    assert format_qa_snippet(None) is None
    assert format_qa_snippet("   \n ") is None
    assert format_qa_snippet("a   b\n c") == "a b c"


def test_format_qa_snippet_truncates():
    out = format_qa_snippet("x" * 200, max_len=10)
    assert out is not None and len(out) == 10
    assert out.startswith("x" * 9)


def test_format_qa_snippet_keeps_filename_of_tokens():
    out = format_qa_snippet(f"see [[file:{A}|report.pdf]] now")
    assert out is not None
    assert "report.pdf" in out
    assert A not in out
