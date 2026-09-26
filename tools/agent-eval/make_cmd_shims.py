"""make_cmd_shims.py [PYTHON] -- write bin/adrpy, bin/adrpy-skills (bash) and their .cmd twins.

Every shim runs the frozen copy in pkg/ under PYTHON (default: this interpreter), logs the call
to $R44_SHIMLOG and forces HOME/USERPROFILE to $R44_TOOL_HOME, so '--target global' (or any
Path.home() fallback) never reaches the real user profile. Called by refreeze.sh (step 0).
"""
import os, sys
F = os.path.dirname(os.path.abspath(__file__))
PY = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else sys.executable)
FM, PYM = F.replace("\\", "/"), PY.replace("\\", "/")
os.makedirs(os.path.join(F, "bin"), exist_ok=True)
for name, mod in (("adrpy", "adrpy"), ("adrpy-skills", "adrpy.skills")):
    sh = [
        "#!/usr/bin/env bash",
        "# agent-eval shim: runs the frozen adrpy copy (see pkg/SOURCE_COMMIT) under the base interpreter.",
        "# HOME/USERPROFILE are forced into scratch so '--target global' (or any",
        "# Path.home() fallback) can never reach the real user profile.",
        f'_th="${{R44_TOOL_HOME:-{FM}/env/tool-home-default}}"',
        'mkdir -p "$_th"',
        f"printf '%s\\t%s\\t%s\\t%s\\n' \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"{name}\" \"$PWD\" \"$*\""
        f' >> "${{R44_SHIMLOG:-{FM}/out/shim_calls_unscoped.log}}"',
        f'HOME="$_th" USERPROFILE="$(cygpath -w "$_th" 2>/dev/null || echo "$_th")" PYTHONPATH="{FM}/pkg"'
        f' PYTHONDONTWRITEBYTECODE=1 exec "{PYM}" -B -s -m {mod} "$@"',
    ]
    with open(os.path.join(F, "bin", name), "w", newline="\n") as fh:
        fh.write("\n".join(sh) + "\n")
    lines = [
        "@echo off", "setlocal",
        rf'if "%R44_TOOL_HOME%"=="" (set "_TH={F}\env\tool-home-default") else (set "_TH=%R44_TOOL_HOME%")',
        'if not exist "%_TH%" mkdir "%_TH%"',
        rf'if "%R44_SHIMLOG%"=="" (set "_SL={F}\out\shim_calls_unscoped.log") else (set "_SL=%R44_SHIMLOG%")',
        f'>>"%_SL%" echo cmd {name} %CD% %*',
        'set "HOME=%_TH%"', 'set "USERPROFILE=%_TH%"',
        rf'set "PYTHONPATH={F}\pkg"', "set PYTHONDONTWRITEBYTECODE=1",
        f'"{PY}" -B -s -m {mod} %*',
    ]
    with open(os.path.join(F, "bin", name + ".cmd"), "w", newline="\r\n") as fh:
        fh.write("\n".join(lines) + "\n")
