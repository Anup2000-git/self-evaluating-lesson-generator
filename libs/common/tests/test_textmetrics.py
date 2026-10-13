from lessongen_common import textmetrics as tm
from lessongen_common.testing import sample_lesson


def test_strip_markdown_removes_syntax_but_keeps_text() -> None:
    md = "## Heading\n\n- **Bold** item with [a link](http://x)\n\n| a | b |\n|---|---|\n| c | d |"
    text = tm.strip_markdown(md)
    assert "Heading" in text
    assert "Bold item with a link" in text
    assert "**" not in text and "](" not in text and "---" not in text


def test_english_only_strips_hindi_hints() -> None:
    text = "Retrieval (खोज कर लाना) means finding information. मनगढ़ंत is a word."
    cleaned = tm.english_only(text)
    assert "खोज" not in cleaned and "मनगढ़ंत" not in cleaned
    assert cleaned.startswith("Retrieval means finding information.")


def test_split_sentences_handles_lines_and_abbreviations() -> None:
    text = "First sentence. Second one, e.g. with an example!\nA list item\nPay Rs. 100 today."
    assert tm.split_sentences(text) == [
        "First sentence.",
        "Second one, e.g. with an example!",
        "A list item",
        "Pay Rs. 100 today.",
    ]


def test_has_script_detects_devanagari() -> None:
    assert tm.has_script("खोज कर लाना", "Hindi") is True
    assert tm.has_script("search", "Hindi") is False
    assert tm.has_script("anything", "Klingon") is None


def test_vocabulary_difficulty_uses_frequency_stems_and_allowlists() -> None:
    assert not tm.is_difficult("students")  # frequent word
    assert not tm.is_difficult("kirana")  # India-familiar allow-list
    assert not tm.is_difficult("company's")  # possessive of a frequent word
    assert tm.is_difficult("multifarious")  # rare word
    assert tm.is_difficult("leverage")  # frequent, but on the academic blocklist
    assert tm.is_difficult("embeddings")
    assert not tm.is_difficult("embeddings", allowed_stems=tm.term_stems("Embedding"))
    assert not tm.is_difficult("retrieves", allowed_stems=tm.term_stems("Retrieval"))


def test_proper_nouns_are_not_counted_as_difficult() -> None:
    sentences = [tm.words(s) for s in ["Riya lives in Patna.", "Then Riya asks a question."]]
    assert tm.difficult_words(sentences) == []


def test_analyze_simple_text() -> None:
    report = tm.analyze("The cat sat. The dog ran fast to the old red barn and sat down.")
    assert report.sentence_count == 2
    assert report.word_count == 15
    assert report.max_sentence_words == 12
    assert report.fk_grade < 5


def test_analyze_flags_long_sentences_and_hard_words() -> None:
    text = (
        "Notwithstanding the multifarious considerations accompanying sophisticated generative "
        "architectures, practitioners must recognise that retrieval paradigms judiciously "
        "amalgamate parametric and non-parametric repositories for epistemic amelioration."
    )
    report = tm.analyze(text, long_sentence_words=20)
    assert report.long_sentences
    assert report.fk_grade > 15
    assert {"multifarious", "amalgamate"} <= set(report.difficult_words)


def test_sample_lesson_is_beginner_friendly() -> None:
    lesson = sample_lesson()
    body = "\n\n".join(s.body_markdown for s in lesson.sections)
    report = tm.analyze(body, allowed_words=[g.term for g in lesson.glossary])
    assert 900 <= report.word_count <= 2000
    assert report.avg_sentence_words <= 15
    assert report.max_sentence_words <= 28
    assert report.fk_grade <= 8.0
