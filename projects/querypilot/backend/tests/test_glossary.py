from types import SimpleNamespace

from app.services.glossary import RetrievedTerm, lexical_matches, prompt_block


def term(name, aliases=()):
    return SimpleNamespace(term=name, aliases=list(aliases))


def test_exact_and_alias_matches_with_plurals():
    terms = [term("revenue", ["sales", "turnover"]), term("active customer"), term("churn")]
    assert [t.term for t in lexical_matches("What was our total sales last year?", terms)] == ["revenue"]
    assert [t.term for t in lexical_matches("How many active customers do we have", terms)] == ["active customer"]
    assert lexical_matches("Show me the film list", terms) == []


def test_word_boundaries_are_respected():
    assert lexical_matches("show prerevenue numbers", [term("revenue")]) == []
    assert lexical_matches("REVENUE by month", [term("revenue")])


def test_prompt_block_formats_definitions_and_sql():
    block = prompt_block([RetrievedTerm(1, "revenue", "Sum of completed payments", "SUM(payment.amount)", "exact")])
    assert "**revenue**: Sum of completed payments" in block and "SUM(payment.amount)" in block
    assert prompt_block([]) == ""
