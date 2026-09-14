"""M3: formula normalization.

Normalization must collapse the differences that are noise (whitespace, case,
bracket/quote form, numeric formatting, comments) and preserve the differences
that are usually the substance of a disagreement (aggregation choice, filter
conditions, date boundaries)."""

from estate_scan.derive.normalize import formula_hash, normalize


def _same(a, b):
    return formula_hash(a) == formula_hash(b)


# -- collapses (noise) -------------------------------------------------------

def test_whitespace_is_collapsed():
    assert _same("SUM([Sales])", "SUM( [Sales] )")
    assert _same("SUM([Sales])  +\n  SUM([Cost])", "SUM([Sales]) + SUM([Cost])")


def test_function_and_identifier_case_is_collapsed():
    assert _same("SUM([Sales])", "sum([sales])")
    assert _same("IF [Active] THEN 1 END", "if [active] then 1 end")


def test_bracket_internal_whitespace_is_collapsed():
    assert _same("[FX Rate]", "[ FX  Rate ]")


def test_quote_form_is_standardized():
    assert _same("[Status] = 'active'", '[Status] = "active"')


def test_numeric_literal_formatting_is_collapsed():
    assert _same("SUM([Sales]) * 1.0", "SUM([Sales]) * 1")
    assert _same(".5 * [X]", "0.5 * [X]")
    assert _same("2e3 + [X]", "2000 + [X]")


def test_comments_are_stripped():
    assert _same("SUM([Sales]) // running total", "SUM([Sales])")
    assert _same("SUM([Sales]) /* note */ + 1", "SUM([Sales]) + 1")


# -- preserved (substance) ---------------------------------------------------

def test_string_literal_content_case_is_preserved():
    assert not _same("[Status] = 'active'", "[Status] = 'ACTIVE'")


def test_aggregation_choice_is_preserved():
    assert not _same("SUM([Sales])", "AVG([Sales])")


def test_date_boundary_is_preserved():
    assert not _same("[D] >= #2024-01-01#", "[D] >= #2024-04-01#")
    assert not _same(
        "IF [Last Order Date] > TODAY() - 30 THEN 1 END",
        "IF [Last Order Date] > TODAY() - 90 THEN 1 END")


def test_filter_condition_is_preserved():
    assert not _same("IF [Orders] > 0 THEN [C] END", "IF [Orders] > 5 THEN [C] END")


def test_digits_inside_a_date_literal_are_not_renumbered():
    # The numeric normalizer must never reach inside a #..# literal; if it did,
    # 2024-01-01 could be mangled and two different boundaries could collide.
    assert normalize("#2024-01-01#") == "#2024-01-01#"


def test_empty_formula_hashes_to_empty():
    assert formula_hash("") == ""
    assert formula_hash(None) == ""
