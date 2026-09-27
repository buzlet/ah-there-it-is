"""Narrow Russian name canonicalization and location relation interpretation.

The morphology analyzer is deliberately used only at entity-name boundaries. It
normalizes words deterministically; it does not rank matches or authorize writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
import unicodedata

import pymorphy3

from ah_there_it_is.domain.names import normalize_name, normalize_search_text


MORPHOLOGY_ENGINE = "pymorphy3-2.0.6+ru-dicts-2.4.417150.4580142"

_SPACE_RE = re.compile(r"\s+")
_WORD_OR_SEPARATOR_RE = re.compile(r"[\w]+(?:-[\w]+)*|[^\w\s]+|\s+", re.UNICODE)
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_LOCATION_PREFIX_RE = re.compile(r"^(?:внутри|во|в|на)\s+", re.IGNORECASE)
_LOCATION_SPLIT_RE = re.compile(r"\s*(?:[,;]\s*)?\s+(внутри|во|в|на)\s+", re.IGNORECASE)

# This is a lexical correction for the observed bathroom use. The analyzer's
# most likely standalone parse for "ванной" is the noun "ванная"; inventory
# location names use the accepted dictionary display form "ванна".
_WORD_OVERRIDES = {"ванной": "ванна"}


@dataclass(frozen=True)
class CanonicalName:
    display_name: str
    comparison_key: str


@dataclass(frozen=True)
class LocationPhrase:
    """A child-first phrase and its relations, with a ready outer-to-inner path."""

    child_first: tuple[str, ...]
    child_to_parent_relations: tuple[str, ...]

    @property
    def outer_to_inner(self) -> tuple[str, ...]:
        return tuple(reversed(self.child_first))

    @property
    def outer_to_inner_relations(self) -> tuple[str, ...]:
        return tuple(reversed(self.child_to_parent_relations))

    @property
    def path_key(self) -> str:
        return " / ".join(normalize_name(part) for part in self.outer_to_inner)


@dataclass(frozen=True)
class ContainmentAssessment:
    decision: str
    rule: str
    child_scale: int | None
    parent_scale: int | None


@lru_cache(maxsize=1)
def _morphology() -> pymorphy3.MorphAnalyzer:
    return pymorphy3.MorphAnalyzer()


def canonicalize_name(value: str) -> CanonicalName:
    """Return canonical Russian entity words and a separate comparison key."""
    return _canonicalize(value, strip_location_prefix=False)


def canonicalize_location_name(value: str) -> CanonicalName:
    """Canonicalize one Location name, removing a leading relation preposition."""
    return _canonicalize(value, strip_location_prefix=True)


def _canonicalize(value: str, *, strip_location_prefix: bool) -> CanonicalName:
    if not isinstance(value, str):
        raise ValueError("name must be text")
    display = _canonical_display(value, strip_location_prefix=strip_location_prefix)
    if not display:
        return CanonicalName(display_name="", comparison_key="")
    return CanonicalName(display_name=display, comparison_key=normalize_name(display))


def _canonical_display(value: str, *, strip_location_prefix: bool) -> str:
    text = unicodedata.normalize("NFKC", value)
    text = text.translate(str.maketrans({
        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-",
        "‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"', "„": '"',
        "«": '"', "»": '"',
    }))
    text = _SPACE_RE.sub(" ", text).strip()
    text = text.strip(" \t\r\n\"'`.,;:!?«»“”„")
    text = _SPACE_RE.sub(" ", text).strip()
    # Relation words are syntax for a Location, but may be ordinary data in an
    # Item, Category or Alias name.
    if strip_location_prefix:
        text = _LOCATION_PREFIX_RE.sub("", text).strip()
    if not text:
        return ""

    chunks: list[tuple[str, str]] = []
    for match in _WORD_OR_SEPARATOR_RE.finditer(text):
        token = match.group(0)
        if token.isspace():
            chunks.append(("space", " "))
        elif token[0].isalnum() or token[0] == "_":
            chunks.append(("word", token))
        else:
            chunks.append(("separator", token))

    parsed: list[tuple[str, str | None, object | None]] = []
    head_seen = False
    dependent_tail = False
    for kind, token in chunks:
        if kind != "word":
            parsed.append((kind, token, None))
            if kind == "separator":
                head_seen = dependent_tail = False
            continue
        canonical, morphology_parse = _canonical_word(token)
        # Complements retain their grammatical case ("плата питания",
        # "щётка для зубов"). Only the head phrase takes dictionary form.
        if head_seen and morphology_parse is not None and (
            "gent" in morphology_parse.tag or morphology_parse.tag.POS == "PREP"
        ):
            dependent_tail = True
        if dependent_tail:
            canonical = token if _LATIN_RE.search(token) else token.casefold()
            morphology_parse = None
        elif morphology_parse is not None and morphology_parse.tag.POS == "NOUN":
            head_seen = True
        parsed.append(("word", canonical, morphology_parse))

    # Lemmatizing an adjective in isolation produces its masculine citation
    # form. Keep adjective+noun phrases grammatical by restoring the head
    # noun's gender and number in nominative case.
    for index, (kind, word, parse) in enumerate(parsed):
        if kind != "word" or parse is None or getattr(parse.tag, "POS", None) != "ADJF":
            continue
        for next_index in range(index + 1, min(len(parsed), index + 5)):
            next_kind, _next_word, next_parse = parsed[next_index]
            if next_kind == "separator":
                break
            if next_kind != "word" or next_parse is None:
                continue
            if getattr(next_parse.tag, "POS", None) == "NOUN":
                grammemes = {"nomn"}
                # Agreement follows the canonical noun, not its original plural
                # or oblique form; otherwise another pass changes the identity.
                noun_tag = next_parse.normalized.tag
                for grammeme in ("femn", "masc", "neut", "plur", "sing"):
                    if grammeme in noun_tag:
                        grammemes.add(grammeme)
                inflected = parse.inflect(grammemes)
                if inflected is not None:
                    prefix = word.rsplit("-", 1)[0] + "-" if "-" in word else ""
                    parsed[index] = (kind, prefix + inflected.word, parse)
                break

    display = "".join(token for _kind, token, _parse in parsed)
    display = _SPACE_RE.sub(" ", display).strip()
    # Cosmetic sentence punctuation is not part of an entity name.
    return display.strip(" \t\r\n.,;:!?\"'`").strip()


def _canonical_word(token: str) -> tuple[str, object | None]:
    # Technical/brand tokens keep their authored casing. Hyphenated mixed
    # identifiers still allow a Russian inflected suffix to reach its lemma.
    if "-" in token:
        parts = token.split("-")
        canonical_parts: list[str] = []
        last_parse: object | None = None
        for part in parts:
            canonical_part, part_parse = _canonical_word(part)
            canonical_parts.append(canonical_part)
            if part_parse is not None:
                last_parse = part_parse
        return "-".join(canonical_parts), last_parse
    if _CYRILLIC_RE.search(token) is None:
        return token, None
    if _LATIN_RE.search(token):
        return token, None

    lowered = token.casefold()
    override = _WORD_OVERRIDES.get(lowered)
    if override is not None:
        return override, None
    parses = _morphology().parse(lowered)
    if not parses:
        return lowered, None
    best = parses[0]
    return best.normal_form.casefold(), best


def parse_location_phrase(value: str) -> LocationPhrase | None:
    """Parse unambiguous Russian child/preposition/parent location chains."""
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFKC", value)
    text = text.translate(str.maketrans({
        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-",
        "‘": "'", "’": "'", "“": '"', "”": '"', "«": '"', "»": '"',
    }))
    text = _SPACE_RE.sub(" ", text).strip(" \t\r\n\"'`.,;:!?")
    if not text:
        return None
    text = _LOCATION_PREFIX_RE.sub("", text).strip()
    if not text:
        return None
    pieces = _LOCATION_SPLIT_RE.split(text)
    if len(pieces) < 3 or len(pieces) % 2 == 0:
        return None
    if "/" in text or len(pieces) > 15:
        raise ValueError("location relation needs clarification: unsupported structured path")
    names: list[str] = []
    relations: list[str] = []
    for index, piece in enumerate(pieces):
        if index % 2 == 0:
            canonical = canonicalize_name(piece).display_name
            if not canonical:
                return None
            names.append(canonical)
        else:
            relation = piece.casefold()
            relations.append("inside" if relation in {"в", "во", "внутри"} else "on")
    if len(names) < 2 or len(names) > 8:
        return None
    if len(relations) != len(names) - 1:
        return None
    return LocationPhrase(tuple(names), tuple(relations))


# Small inspectable size classes for common household locations. Unknown nouns
# stay unknown; physical mode asks for clarification rather than guessing.
_LOCATION_SCALES: dict[str, int] = {
    "дом": 7, "квартира": 6, "комната": 5, "ванна": 5, "кухня": 5,
    "коридор": 5, "кабинет": 5, "гараж": 5, "балкон": 5, "кладовая": 5,
    "шкаф": 4, "тумбочка": 4, "комод": 4, "стол": 4, "письменный стол": 4,
    "стеллаж": 4, "кровать": 4, "диван": 4, "холодильник": 4,
    "ящик": 3, "полка": 3, "подоконник": 3, "корзина": 3, "рюкзак": 3,
    "коробка": 2, "контейнер": 2, "органайзер": 2, "папка": 2, "книга": 2,
    "футляр": 1, "телефон": 1, "ключ": 1, "кабель": 1,
}
_SURFACES = {"стол", "письменный стол", "полка", "стеллаж", "шкаф", "подоконник", "комод", "тумбочка"}


def assess_location_relation(
    child_name: str, parent_name: str, relation: str = "inside"
) -> ContainmentAssessment:
    """Conservatively assess a known household containment/support relation."""
    child_key = normalize_search_text(canonicalize_location_name(child_name).display_name)
    parent_key = normalize_search_text(canonicalize_location_name(parent_name).display_name)
    if child_key == parent_key:
        return ContainmentAssessment("implausible", "same_canonical_location", None, None)

    child_scale = _location_scale(child_key)
    parent_scale = _location_scale(parent_key)
    if relation == "on":
        parent_surface = parent_key in _SURFACES or any(
            f" {surface}" in f" {parent_key}" for surface in _SURFACES
        )
        if not parent_surface:
            decision = "implausible" if parent_scale is not None else "uncertain"
            return ContainmentAssessment(decision, "parent_not_known_surface", child_scale, parent_scale)
        if child_scale is None:
            return ContainmentAssessment("uncertain", "unknown_child_size", child_scale, parent_scale)
        if parent_scale is not None and child_scale < parent_scale:
            return ContainmentAssessment("plausible", "known_object_on_surface", child_scale, parent_scale)
        if parent_scale is not None and child_scale > parent_scale:
            return ContainmentAssessment("implausible", "child_materially_larger_than_surface", child_scale, parent_scale)
        return ContainmentAssessment("uncertain", "relative_size_not_established", child_scale, parent_scale)

    if relation != "inside":
        return ContainmentAssessment("uncertain", "unknown_relation", child_scale, parent_scale)
    if child_scale is None or parent_scale is None:
        return ContainmentAssessment("uncertain", "unknown_size_class", child_scale, parent_scale)
    if child_scale > parent_scale:
        return ContainmentAssessment("implausible", "child_materially_larger_than_parent", child_scale, parent_scale)
    if child_scale == parent_scale:
        return ContainmentAssessment("uncertain", "relative_size_not_established", child_scale, parent_scale)
    return ContainmentAssessment("plausible", "known_household_scale_order", child_scale, parent_scale)


def _location_scale(name_key: str) -> int | None:
    exact = _LOCATION_SCALES.get(name_key)
    if exact is not None:
        return exact
    words = name_key.split()
    matches = [
        scale for term, scale in _LOCATION_SCALES.items()
        if term in words
    ]
    return max(matches) if matches else None
