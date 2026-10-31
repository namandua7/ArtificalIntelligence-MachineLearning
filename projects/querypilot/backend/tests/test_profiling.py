from app.services.profiling import clean_values, is_candidate, plausible


def col(name, type_="character varying(25)", pk=False, fk=None):
    return {"name": name, "type": type_, "pk": pk, "fk": fk, "nullable": True, "comment": None}


def test_candidates_are_text_enum_bool_only():
    assert is_candidate(col("name"))
    assert is_candidate(col("rating", "mpaa_rating"))
    assert is_candidate(col("active", "boolean"))
    assert not is_candidate(col("film_id", "integer"))
    assert not is_candidate(col("amount", "numeric(5,2)"))
    assert not is_candidate(col("created", "timestamp without time zone"))
    assert not is_candidate(col("tags", "text[]"))
    assert not is_candidate(col("id", "character varying", pk=True))
    assert not is_candidate(col("country_code", "character varying", fk="country.code"))


def test_sensitive_columns_are_never_profiled():
    for name in ("email", "customer_email", "phone_number", "password_hash", "first_name", "last_name",
                 "address", "ssn", "api_key", "card_number"):
        assert not is_candidate(col(name)), name


def test_plausible_uses_planner_stats():
    assert plausible(5, 1000, 40)
    assert not plausible(500, 1000, 40)
    assert plausible(-0.001, 10_000, 40)  # fraction of rows → ~10 distinct
    assert not plausible(-0.5, 10_000, 40)
    assert not plausible(0, 10, 40)
    assert plausible(None, 500, 40)  # never analyzed, small table → scan
    assert not plausible(None, 50_000_000, 40)


def test_clean_values():
    assert clean_values(["G", " PG ", "R"], 40) == ["G", "PG", "R"]
    assert clean_values(["a"] * 41, 40) is None  # high cardinality
    assert clean_values(["x" * 100], 40) is None  # free text
    assert clean_values(["", "  "], 40) is None
