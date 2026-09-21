"""String case transforms, used both to build a filename's title segment
and to compute the case-insensitive-ish key `new`/`version`/`supersede`
use to detect a duplicate title (PascalCase applied *on top of* the
repo's configured case-transform, giving a comparison key independent of
casetransform)."""

import re

_WORD_SPLIT_PATTERN = re.compile(r"(?<!^)(?=[A-Z][a-z])|(?<=[a-z])(?=[A-Z])|[\s_-]+")


def _split_into_words(text):
    if not text or not text.strip():
        return []
    return [word for word in _WORD_SPLIT_PATTERN.split(text.strip()) if word]


def to_camel_case(text):
    words = _split_into_words(text)
    if not words:
        return text
    first, *rest = words
    return first.lower() + "".join(word[:1].upper() + word[1:].lower() for word in rest)


def to_pascal_case(text):
    words = _split_into_words(text)
    if not words:
        return text
    return "".join(word[:1].upper() + word[1:].lower() for word in words)


def to_snake_case(text):
    words = _split_into_words(text)
    if not words:
        return text
    return "_".join(word.lower() for word in words)


def to_kebab_case(text):
    words = _split_into_words(text)
    if not words:
        return text
    return "-".join(word.lower() for word in words)


CASE_TRANSFORMS = {
    "CamelCase": to_camel_case,
    "PascalCase": to_pascal_case,
    "SnakeCase": to_snake_case,
    "KebabCase": to_kebab_case,
}


def to_case(text, case_format):
    return CASE_TRANSFORMS[case_format](text)


def unique_title_key(title, config):
    """The repo's configured case-transform, then PascalCase again on
    top, as the canonical comparison key regardless of casetransform."""
    return to_pascal_case(to_case(title, config.casetransform))
