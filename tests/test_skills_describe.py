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
