# installconfig never named its own per-user path convention

**Front:** Usability | **Severity:** Low | **Resolution:** Direct | **Round:** 11

`installconfig.py`'s own module docstring and `describe()` said it operates on "the one, fixed, per-user location," but never named the actual convention (`%APPDATA%\adrpy\install-config.json` / `~/.config/adrpy/install-config.json`) or pointed out that the `file` key in every response is the only way to discover it without reading source.

**Fix:** module docstring now names the convention explicitly. Minor -- the path is always in the result -- so no `describe()` change beyond what was already there. adrpy-ai `1b53975`.
