from app.services.schema_text import MAX_COLUMNS, compact_table, short_type


def col(name, type_="integer", pk=False, fk=None):
    return {"name": name, "type": type_, "pk": pk, "fk": fk}


def test_short_type():
    assert short_type("character varying(255)") == "varchar"
    assert short_type("integer") == "int"
    assert short_type("timestamp without time zone") == "timestamp"
    assert short_type("numeric(5,2)") == "numeric(5,2)"
    assert short_type("text[]") == "text[]"
    assert short_type("mpaa_rating") == "mpaa_rating"


def test_compact_line_has_pk_fk_values_and_row_estimate():
    line = compact_table(
        "film", "table",
        [col("film_id", pk=True), col("language_id", fk="language.language_id"),
         col("rating", "mpaa_rating"), col("title", "character varying(255)")],
        row_estimate=1000, comment="Films",
        values={"rating": ["G", "PG", "PG-13"]},
    )
    assert line == ("film (~1,000) -- Films: film_id int PK, language_id int→language.language_id, "
                    "rating mpaa_rating{G|PG|PG-13}, title varchar")


def test_values_and_columns_are_capped_and_views_marked():
    wide = [col(f"c{i}") for i in range(MAX_COLUMNS + 5)]
    line = compact_table("v", "view", wide, values={"c0": [str(i) for i in range(20)]})
    assert line.startswith("VIEW v:") and "…+5 more columns" in line
    assert "c0 int{0|1|2|3|4|5|6|7|…}" in line


def test_far_smaller_than_stored_summary():
    from app.services.indexing import build_summary
    from app.services.target import IntrospectedTable

    cols = [dict(col(f"col_{i}", "character varying(100)"), nullable=True, comment=None) for i in range(10)]
    stored = build_summary(IntrospectedTable("public", "t", "table", None, 5000, cols), [])
    assert len(compact_table("t", "table", cols, 5000)) < len(stored) * 0.7
