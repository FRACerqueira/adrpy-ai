import json
from importlib import resources


def test_locale_files_have_matching_keys():
    package = resources.files("adrpy.resources.locale")
    en_keys = set(json.loads(package.joinpath("en.json").read_text(encoding="utf-8")))
    pt_keys = set(json.loads(package.joinpath("pt-BR.json").read_text(encoding="utf-8")))

    assert en_keys == pt_keys
