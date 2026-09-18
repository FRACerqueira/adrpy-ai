# installconfig's folderadr description overstated its own escape-path enforcement

**Front:** Usability | **Severity:** Low | **Resolution:** Direct | **Round:** 11

`installconfig.py`'s `folderadr` description claimed the same escape-path rule `config`'s own `--folderadr` enforces applies here too. It doesn't: `installconfig` only rejects empty/absolute values (via `parse_repo_config`'s `_is_relative_path`), never a relative escape like `"../../evil"` -- the real escape check (`resolve_within`) only runs later, inside whichever command consumes this file as a seed (`init`). `installconfig --folderadr "../../evil"` succeeds silently today; the bad value only surfaces as a failure from `init`, a different command than the one that accepted it.

**Fix:** description now states plainly what is and isn't checked here, and where the real check happens. No code change -- whether `installconfig` should pre-validate the escape shape itself is a separate design question, not raised as urgent by this pass. adrpy-ai `1b53975`.
