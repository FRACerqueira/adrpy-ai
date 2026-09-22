from adrpy.skills.registry import COMMANDS


def test_every_command_name_matches_its_registry_key():
    for key, module in COMMANDS.items():
        assert module.describe()["name"] == key


def test_every_command_describe_has_the_expected_shape():
    for module in COMMANDS.values():
        info = module.describe()
        assert isinstance(info["summary"], str) and info["summary"]
        assert isinstance(info["description"], str) and info["description"]
        assert isinstance(info["arguments"], list)
        for arg in info["arguments"]:
            assert set(arg) >= {"name", "type", "required", "description"}
            assert arg["type"] in ("string", "switch")
        assert isinstance(info["failure_codes"], list) and info["failure_codes"]
        for code in info["failure_codes"]:
            assert set(code) == {"code", "condition"}


def test_every_command_documents_usage_error():
    for module in COMMANDS.values():
        codes = {c["code"] for c in module.describe()["failure_codes"]}
        assert "usage-error" in codes


def test_install_and_remove_document_target_global_restriction():
    for name in ("install", "remove"):
        info = COMMANDS[name].describe()
        text = info["description"]
        assert "global" in text and "usage-error" in text


def test_short_flag_aliases_are_documented_in_describe():
    """Mirrors adrpy's own test_help.py::test_short_flag_aliases_are_
    documented_in_describe -- every command's real parse_flags(aliases=...)
    accepts a short form, and describe() must expose it the same way."""
    expected = {
        "install": {"provider": "-p", "target": "-t", "skill": "-s", "force": "-f"},
        "remove": {"provider": "-p", "target": "-t", "skill": "-s", "force": "-f"},
        "list": {"provider": "-p", "skill": "-s"},
    }
    for name, aliases in expected.items():
        by_name = {arg["name"]: arg for arg in COMMANDS[name].describe()["arguments"]}
        for field, alias in aliases.items():
            assert by_name[field].get("alias") == alias, f"{name}'s '{field}' argument doesn't document '{alias}'"


def test_describe_arguments_match_what_run_actually_accepts_via_parse_flags():
    """Round 32, Class I: cross-checks describe()'s documented arguments
    against the flags parse_flags(...) actually declares inside run(), via
    a source-level scan of each command module -- so the two can never
    silently drift apart (e.g. a new flag added to parse_flags but never
    documented, or vice versa)."""
    import ast
    import inspect

    from adrpy.skills.commands import help as help_command
    from adrpy.skills.commands import install as install_command
    from adrpy.skills.commands import list as list_command
    from adrpy.skills.commands import remove as remove_command

    modules = {
        "install": install_command,
        "remove": remove_command,
        "list": list_command,
    }
    for name, module in modules.items():
        source = inspect.getsource(module.run)
        tree = ast.parse(source)
        call = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", None)) == "parse_flags"
        )
        declared = set()
        for kw in call.keywords:
            if kw.arg in ("required", "optional", "switches") and isinstance(kw.value, ast.Tuple):
                declared |= {element.value for element in kw.value.elts}
        documented = {arg["name"] for arg in module.describe()["arguments"] if not arg.get("positional")}
        assert declared == documented, f"{name}: parse_flags declares {declared}, describe() documents {documented}"

    # help.py doesn't use parse_flags (it hand-parses --full/positional
    # command), so it's checked separately against what it actually reads.
    help_documented = {arg["name"] for arg in help_command.describe()["arguments"]}
    assert help_documented == {"command", "full"}
