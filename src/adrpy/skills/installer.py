"""install/remove/list logic for adrpy-skills: resolves each (provider,
skill) pair to a real path, builds its content via that provider's wrap,
and checks/writes it through the content-hash drift marker -- see
ADR009V01."""

import re
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path

from adrpy.core.errors import UsageError
from adrpy.core.hashing import build_marker, check_drift
from adrpy.skills import resources
from adrpy.skills.providers import PROVIDERS, SHARED_DOC_PATH

_FRONTMATTER_RE = re.compile(r"\A(---\n.*?\n---\n)", re.DOTALL)


def _package_version():
    try:
        return _pkg_version("adrpy-ai")
    except PackageNotFoundError:
        return "0.0.0+dev"


def _resolve_path(provider_name, skill_name, target_dir, scope):
    spec = PROVIDERS[provider_name]
    if scope == "global":
        template = spec["global_path"]
        if template is None:
            raise UsageError(f"--target global is not supported for provider '{provider_name}'.")
        return Path.home() / template[len("~/") :].format(name=skill_name)
    return Path(target_dir) / spec["project_path"].format(name=skill_name)


def _insert_marker(content, marker_version):
    """Places the marker immediately after a leading frontmatter block if
    one is present, otherwise at the very start -- the hash always covers
    `content` exactly as given, never the marker line itself.

    Must stay an exact inverse of `core.hashing.strip_marker` (which
    removes the marker line plus exactly one trailing newline): inserting
    `marker + "\\n"` and nothing else guarantees `strip_marker(insert_
    marker(content, v)) == content` for any content, so a freshly
    (re)generated file always re-hashes as "clean", never "drifted"."""
    marker = build_marker(marker_version, content)
    match = _FRONTMATTER_RE.match(content)
    if match:
        end = match.end()
        return content[:end] + marker + "\n" + content[end:]
    return marker + "\n" + content


def _shared_doc_path(target_dir, skill_name):
    return Path(target_dir) / SHARED_DOC_PATH.format(name=skill_name)


def _build_shared_doc_content(skill_name, full_content):
    return f"# {skill_name}\n\n{full_content}"


_AGENTSMD_BLOCK_TEMPLATE = "<!-- adrpy:skills:{name}:start -->\n{body}<!-- adrpy:skills:{name}:end -->\n"


def _agentsmd_block_pattern(skill_name):
    escaped = re.escape(skill_name)
    return re.compile(
        r"<!-- adrpy:skills:" + escaped + r":start -->\n.*?<!-- adrpy:skills:" + escaped + r":end -->\n?",
        re.DOTALL,
    )


def _agentsmd_extract_block(file_text, skill_name):
    match = _agentsmd_block_pattern(skill_name).search(file_text)
    return match.group(0) if match else None


def _agentsmd_inner_pattern(skill_name):
    escaped = re.escape(skill_name)
    return re.compile(
        r"<!-- adrpy:skills:" + escaped + r":start -->\n(.*?)<!-- adrpy:skills:" + escaped + r":end -->\n?",
        re.DOTALL,
    )


def _agentsmd_extract_inner(file_text, skill_name):
    """The block's own content, excluding the `start`/`end` wrapper lines
    -- this is what was actually hashed (`marker + inner`), so drift
    checks must run against this, never the whole wrapped block."""
    match = _agentsmd_inner_pattern(skill_name).search(file_text)
    return match.group(1) if match else None


def _agentsmd_replace_or_append(file_text, skill_name, new_block):
    pattern = _agentsmd_block_pattern(skill_name)
    if pattern.search(file_text):
        return pattern.sub(lambda _m: new_block, file_text, count=1)
    if not file_text:
        return new_block
    sep = "\n" if file_text.endswith("\n") else "\n\n"
    return file_text + sep + new_block


def _agentsmd_remove_block(file_text, skill_name):
    return _agentsmd_block_pattern(skill_name).sub("", file_text, count=1)


def _agentsmd_has_any_block(file_text):
    return bool(re.search(r"<!-- adrpy:skills:[^:]+:start -->", file_text or ""))


def _other_stub_providers_reference(target_dir, skill_name, scope, exclude_provider, providers_in_target):
    """True if some OTHER stub-mode provider (already installed, not part
    of this same call, or part of it but not the one being removed) still
    points at the shared doc for this skill."""
    for provider_name, spec in PROVIDERS.items():
        if provider_name == exclude_provider or spec["mode"] not in ("stub", "stub_block"):
            continue
        if scope == "global" and spec["global_path"] is None:
            continue
        path = _resolve_path(provider_name, skill_name, target_dir, scope)
        if provider_name == "agentsmd":
            if path.exists() and _agentsmd_extract_block(path.read_text(encoding="utf-8"), skill_name):
                return True
        elif path.exists():
            return True
    return False


def _expand(names, universe):
    if not names or names == ["all"]:
        return list(universe)
    unknown = [n for n in names if n not in universe]
    if unknown:
        raise UsageError(f"Unknown value(s): {', '.join(unknown)}")
    return list(names)


def install(target_dir, providers, skills, scope, force):
    provider_names = _expand(providers, PROVIDERS)
    skill_names = _expand(skills, resources.SKILL_NAMES)
    marker_version = _package_version()
    installed = []
    skipped = []

    for skill_name in skill_names:
        meta = resources.load_meta(skill_name)
        full_content = resources.load_full_content(skill_name)
        shared_doc_rel = SHARED_DOC_PATH.format(name=skill_name)
        needs_shared_doc = False

        for provider_name in provider_names:
            spec = PROVIDERS[provider_name]
            if scope == "global" and spec["global_path"] is None:
                raise UsageError(f"--target global is not supported for provider '{provider_name}'.")

            if provider_name == "agentsmd":
                path = _resolve_path(provider_name, skill_name, target_dir, scope)
                existing_file = path.read_text(encoding="utf-8") if path.exists() else ""
                existing_inner = _agentsmd_extract_inner(existing_file, skill_name)
                status = check_drift(existing_inner)
                if status in ("drifted", "foreign") and not force:
                    skipped.append({"provider": provider_name, "skill": skill_name, "file": str(path), "reason": status})
                    continue
                inner = spec["wrap"](skill_name, meta, None, shared_doc_rel)
                marker = build_marker(marker_version, inner)
                body = marker + "\n" + inner
                new_block = _AGENTSMD_BLOCK_TEMPLATE.format(name=skill_name, body=body)
                new_file = _agentsmd_replace_or_append(existing_file, skill_name, new_block)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(new_file, encoding="utf-8")
                installed.append({"provider": provider_name, "skill": skill_name, "file": str(path)})
                needs_shared_doc = True
                continue

            path = _resolve_path(provider_name, skill_name, target_dir, scope)
            existing = path.read_text(encoding="utf-8") if path.exists() else None
            status = check_drift(existing)
            if status in ("drifted", "foreign") and not force:
                skipped.append({"provider": provider_name, "skill": skill_name, "file": str(path), "reason": status})
                continue

            if spec["mode"] == "full":
                wrapped = spec["wrap"](skill_name, meta, full_content, None)
            else:
                wrapped = spec["wrap"](skill_name, meta, None, shared_doc_rel)
                needs_shared_doc = True
            content = _insert_marker(wrapped, marker_version)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            installed.append({"provider": provider_name, "skill": skill_name, "file": str(path)})

        if needs_shared_doc:
            shared_path = _shared_doc_path(target_dir, skill_name)
            shared_existing = shared_path.read_text(encoding="utf-8") if shared_path.exists() else None
            shared_status = check_drift(shared_existing)
            if shared_status in ("drifted", "foreign") and not force:
                skipped.append({"provider": "shared-doc", "skill": skill_name, "file": str(shared_path), "reason": shared_status})
            else:
                shared_content = _insert_marker(_build_shared_doc_content(skill_name, full_content), marker_version)
                shared_path.parent.mkdir(parents=True, exist_ok=True)
                shared_path.write_text(shared_content, encoding="utf-8")

    return {"installed": installed, "skipped": skipped, "warnings": []}


def remove(target_dir, providers, skills, scope, force):
    provider_names = _expand(providers, PROVIDERS)
    skill_names = _expand(skills, resources.SKILL_NAMES)
    removed = []
    warnings = []

    for skill_name in skill_names:
        shared_doc_rel = SHARED_DOC_PATH.format(name=skill_name)
        any_stub_removed = False

        for provider_name in provider_names:
            spec = PROVIDERS[provider_name]
            if scope == "global" and spec["global_path"] is None:
                raise UsageError(f"--target global is not supported for provider '{provider_name}'.")

            if provider_name == "agentsmd":
                path = _resolve_path(provider_name, skill_name, target_dir, scope)
                if not path.exists():
                    warnings.append(f"agentsmd/{skill_name}: not installed, nothing to remove.")
                    continue
                file_text = path.read_text(encoding="utf-8")
                inner = _agentsmd_extract_inner(file_text, skill_name)
                if inner is None:
                    warnings.append(f"agentsmd/{skill_name}: not installed, nothing to remove.")
                    continue
                status = check_drift(inner)
                if status == "drifted" and not force:
                    warnings.append(f"agentsmd/{skill_name}: drifted, skipped (use --force to remove anyway).")
                    continue
                new_file = _agentsmd_remove_block(file_text, skill_name)
                # Never delete AGENTS.md itself, even if this empties it --
                # that's a judgment call for the human, not this command.
                path.write_text(new_file, encoding="utf-8")
                removed.append({"provider": provider_name, "skill": skill_name, "file": str(path)})
                any_stub_removed = True
                continue

            path = _resolve_path(provider_name, skill_name, target_dir, scope)
            if not path.exists():
                warnings.append(f"{provider_name}/{skill_name}: not installed, nothing to remove.")
                continue
            existing = path.read_text(encoding="utf-8")
            status = check_drift(existing)
            if status == "drifted" and not force:
                warnings.append(f"{provider_name}/{skill_name}: drifted, skipped (use --force to remove anyway).")
                continue
            path.unlink()
            removed.append({"provider": provider_name, "skill": skill_name, "file": str(path)})
            if spec["mode"] in ("stub", "stub_block"):
                any_stub_removed = True

        if any_stub_removed:
            still_referenced = _other_stub_providers_reference(target_dir, skill_name, scope, None, provider_names)
            if not still_referenced:
                shared_path = _shared_doc_path(target_dir, skill_name)
                if shared_path.exists():
                    shared_path.unlink()
                    removed.append({"provider": "shared-doc", "skill": skill_name, "file": str(shared_path)})

    return {"removed": removed, "warnings": warnings}


def list_installed(target_dir, providers, skills):
    provider_names = _expand(providers, PROVIDERS)
    skill_names = _expand(skills, resources.SKILL_NAMES)
    rows = []

    for skill_name in skill_names:
        for provider_name in provider_names:
            spec = PROVIDERS[provider_name]
            scopes = ("project", "global") if provider_name == "claude" else ("project",)
            for scope in scopes:
                if scope == "global" and spec["global_path"] is None:
                    continue
                path = _resolve_path(provider_name, skill_name, target_dir, scope)
                if provider_name == "agentsmd":
                    file_text = path.read_text(encoding="utf-8") if path.exists() else ""
                    inner = _agentsmd_extract_inner(file_text, skill_name)
                    installed_flag = inner is not None
                    # "foreign" counts as drifted here too: both mean install/remove
                    # would refuse to touch this path without --force, which is the
                    # one thing this boolean needs to tell the caller.
                    drifted = None if not installed_flag else check_drift(inner) in ("drifted", "foreign")
                else:
                    existing = path.read_text(encoding="utf-8") if path.exists() else None
                    installed_flag = existing is not None
                    drifted = None if not installed_flag else check_drift(existing) in ("drifted", "foreign")
                rows.append(
                    {
                        "skill": skill_name,
                        "provider": provider_name,
                        "scope": scope,
                        "installed": installed_flag,
                        "drifted": drifted,
                        "file": str(path),
                    }
                )

    return {"skills": rows}
