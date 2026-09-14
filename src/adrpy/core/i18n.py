"""Locale loading for human-readable text (harness Fase 2).

JSON contract keys/values (the `success`/`data`/`code` envelope) are
never translated -- only text meant for a human to read (--help
descriptions, error details) goes through this.
"""

import json
from functools import lru_cache
from importlib import resources

DEFAULT_LANGUAGE = "en"


@lru_cache
def _catalog(language):
    package = resources.files("adrpy.resources.locale")
    resource = package.joinpath(f"{language}.json")
    if not resource.is_file():
        resource = package.joinpath(f"{DEFAULT_LANGUAGE}.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def translate(key, language=DEFAULT_LANGUAGE, **kwargs):
    text = _catalog(language)[key]
    return text.format(**kwargs) if kwargs else text
