from evaluator_svc.checks.evidence import quote_found
from evaluator_svc.context import normalize_for_match

LESSON = normalize_for_match(
    "Step 2 is the question.\n\n"
    "Step 3 is retrieve. The user question becomes a **query** (सवाल या खोज). "
    "The **retriever** (खोजकर लाने वाला भाग) searches the index.\n\n"
    "Step 4 is augment. The found text is added to the prompt.\n\n"
    "Step 5 is generate. RAG does not change **model weights** (मॉडल के अंदर के नंबर). "
    "RAG only changes the prompt for this one question."
)


def test_quote_that_drops_bracketed_hindi_hints_is_found() -> None:
    quote = "The user question becomes a query. The retriever searches the index."
    assert quote_found(quote, LESSON, 88)


def test_quote_stitched_from_verbatim_sentences_is_found() -> None:
    # Seen live: the simulated learner quoted the start of three paragraphs as one quote.
    assert quote_found("Step 3 is retrieve.\nStep 4 is augment.\nStep 5 is generate.", LESSON, 88)


def test_invented_sentence_is_still_rejected() -> None:
    assert not quote_found("RAG retrains the model every night on new documents.", LESSON, 88)
    # One invented sentence among real ones fails the whole quote.
    assert not quote_found(
        "Step 3 is retrieve. RAG retrains the model every night on new documents.", LESSON, 88
    )
