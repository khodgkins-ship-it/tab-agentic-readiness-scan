"""Formula normalization (build spec section 7.2).

Applied to *resolved* formulas before hashing. The goal is that two formulas
which express the same logic collapse to one hash, while any difference that is
usually the substance of a disagreement is preserved.

    Normalize away        comments, whitespace, identifier/function case,
                          bracket and quote form, numeric literal formatting
    Preserve              filter conditions, date boundaries (# .. #),
                          aggregation choices, string literal content

We deliberately UNDER-normalize (build brief section 6): a false variant is a
cheap error, a missed conflict is an expensive one. So this module does not
attempt algebraic simplification and does not sort commutative argument lists.
Commutative-argument sorting is listed in the spec as a "where safe" option; it
is omitted in the prototype because deciding what is safe in a flat token stream
is exactly the kind of guess that manufactures false collapses. See
REPORT-BACK.md section 4.

Implementation is a small lexer rather than a chain of regex substitutions,
because the correctness hazard here is normalizing digits inside a date literal
or lowercasing the contents of a string literal. Tokenizing first makes those
categories impossible to touch by accident.
"""

import hashlib
import re

# One token per alternative. Order matters: comments and literals are matched
# before the general word/number/operator classes so their contents are never
# reinterpreted. re.DOTALL lets a block comment span newlines.
_TOKEN_RE = re.compile(
    r"""
      (?P<block>/\*.*?\*/)                        # /* block comment */
    | (?P<line>//[^\n\r]*)                        # // line comment
    | (?P<dstr>"(?:[^"\\]|\\.)*")                 # "double string"
    | (?P<sstr>'(?:[^'\\]|\\.)*')                 # 'single string'
    | (?P<date>\#[^#]*\#)                         # #date literal#
    | (?P<ident>\[[^\]]*\])                       # [Bracketed Field]
    | (?P<num>(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)
    | (?P<word>[^\W\d]\w*)                         # function / bare identifier
    | (?P<op><=|>=|<>|!=|==|[-+*/%^()<>=,.:!&|~{}])
    | (?P<ws>\s+)
    | (?P<other>.)
    """,
    re.VERBOSE | re.DOTALL | re.UNICODE,
)


def _norm_number(tok):
    # type: (str) -> str
    """Canonicalize numeric literal formatting: 1.0 -> 1, .5 -> 0.5, 2e3 -> 2000.

    A pure integer token is kept on the integer path (only stripping leading
    zeros) so large integers never lose precision through float().
    """
    if re.match(r"^\d+$", tok):
        return str(int(tok))
    value = float(tok)
    if value == int(value):
        return str(int(value))
    return repr(value)


def _norm_string(inner):
    # type: (str) -> str
    """Standardize quote form to double quotes, preserving content case.

    Escaped quotes inside a literal are not re-escaped in the prototype; string
    literals are rare in these formulas and this is noted as a known limitation.
    """
    return '"' + inner + '"'


def _norm_ident(inner):
    # type: (str) -> str
    """Lowercase a bracketed identifier and collapse internal whitespace."""
    return "[" + " ".join(inner.split()).lower() + "]"


def normalize(formula):
    # type: (str) -> str
    """Return the normalized token stream for a (resolved) formula.

    Tokens are joined with single spaces. The result is meant for hashing and
    comparison, not for display; the human-readable form is the resolved
    formula stored alongside it.
    """
    if not formula:
        return ""
    pieces = []  # type: list
    for m in _TOKEN_RE.finditer(formula):
        kind = m.lastgroup
        text = m.group()
        if kind == "block" or kind == "line" or kind == "ws":
            continue
        if kind == "date":
            pieces.append(text)                       # preserve verbatim
        elif kind == "dstr":
            pieces.append(_norm_string(text[1:-1]))
        elif kind == "sstr":
            pieces.append(_norm_string(text[1:-1]))
        elif kind == "ident":
            pieces.append(_norm_ident(text[1:-1]))
        elif kind == "num":
            pieces.append(_norm_number(text))
        elif kind == "word":
            pieces.append(text.lower())
        else:  # op / other
            pieces.append(text)
    return " ".join(pieces)


def formula_hash(formula):
    # type: (str) -> str
    """Stable hash of the normalized form. Empty formula hashes to ''."""
    norm = normalize(formula)
    if not norm:
        return ""
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()
