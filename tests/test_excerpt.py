"""The citation excerpt shows the passage that supports the claim (app/excerpt.py)."""

from app.excerpt import LIMIT, best_passage, pieces, stem

FILLER = "\n\n".join(f"Failure to maintain item number {n} as required by the building rules;" for n in range(12))
SECTION = (FILLER + "\n\nFailure to exterminate insects, rodents or other pests;\n\n"
           "Failure to supply heat as required by the municipal code.")


def test_stems_group_word_forms_and_drop_common_words():
    assert stem("rodents") == stem("rodent") == "rodent"
    assert stem("heating") == stem("heats") == "heat"
    assert stem("the") is None and stem("shall") is None and stem("a") is None
    assert stem("914,383,396") == "914383396" and stem("8:30") == "8:30"


def test_picks_the_passage_behind_the_claim_not_the_start():
    e = best_passage(SECTION, "Landlords must exterminate rodents.")
    assert "exterminate insects, rodents" in e.text and e.text.startswith("…")
    assert len(e.text) <= LIMIT + 2
    assert {"exterminate", "rodents"} <= set(e.highlights)


def test_without_a_match_the_excerpt_is_the_start():
    e = best_passage(SECTION, "")
    assert e.text.startswith("Failure to maintain item number 0") and e.text.endswith("…") and e.highlights == []


def test_a_repeated_word_doesnt_beat_distinct_matches():
    body = ("Heat heat heat heat heat heat.\n\n" + "x " * 250 + "\n\n"
            "The minimum heat at night is 66 degrees.")
    e = best_passage(body, "What minimum heat is required at night? 66 degrees", limit=60)
    assert "66 degrees" in e.text


def test_budget_numbers_pin_the_table_row():
    rows = "\n".join(f"Department {n} | 1,000,{n:03d} | 2,000,{n:03d}" for n in range(30))
    body = "Department | 2026 | 2027\n" + rows + "\nChicago Fire Department | 907,646,972 | 914,383,396"
    e = best_passage(body, "The Fire Department's proposed 2027 budget is $914,383,396.")
    assert "Chicago Fire Department | 907,646,972 | 914,383,396" in e.text and "914,383,396" in e.highlights
    assert "\n" in e.text   # table rows keep their own lines


def test_pdf_line_wraps_become_spaces_and_times_dont_end_sentences():
    body = "68°F at 8:30 a.m. and\nthereafter until 10:30 p.m. In all rooms. Next rule here."
    assert [p for _, p in pieces(body)] == [
        "68°F at 8:30 a.m. and thereafter until 10:30 p.m. In all rooms.", "Next rule here."]


def test_excerpt_starts_at_a_matching_sentence_not_the_filler_before_it():
    body = ("Opening words about something else entirely. " * 4 + "\n\n"
            "The landlord shall give the tenant two days notice before entry.\n\nClosing text.")
    e = best_passage(body, "Two days notice before entering.")
    assert e.text.startswith("…The landlord shall give")
