<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← README](../../README.md) · [Command Reference](../commands/INDEX.md) · [Decision-log workflow](../decision-log-workflow.md)

# `adrpy-skills`: installing the judgment layer

`adrpy` manages the ADR/decision-log *record* -- it never decides when a
decision needs recording, when a hardening review is due, or when to close
a review cycle. That judgment already exists as three vendor-neutral AI
coding-agent skills (`decision-log`, `pre-release-audit`, `comment-audit`).
`adrpy-skills` installs those skills into a repository (or your own global
config), for whichever AI coding assistants you actually use. See
[ADR009V01](../adr/ADR009V01-ai-coding-agent-skills-installer-ships-as-a-separate-adrpy-skills-entry-point-with-per-provider-full-body-or-stub-delivery.md)
for the full design rationale -- this page is the *how*, not the *why*.

## Two commands, one package, no runtime coupling

`adrpy-skills` is a **separate console-script entry point**, not a
subcommand of `adrpy`. They ship in the same pip distribution (`pip install
adrpy-ai` gives you both `adrpy` and `adrpy-skills` as two independent
executables on your `PATH`), but neither one calls the other at runtime,
and `adrpy`'s own command surface (`adrpy help`, every `describe()`
contract) never mentions `adrpy-skills` at all. Installing or using
`adrpy-skills` is entirely opt-in -- `adrpy` itself works exactly the same
with or without it ever being run.

## What actually gets installed

For each requested skill, the *content* delivered is up to three static
pieces, concatenated in this order:

1. **`gate.md`** (when the skill has one) -- *when* this skill is allowed
   to run, rewritten to stand on its own without the maintainer's personal
   global instructions. `pre-release-audit` and `decision-log` both have
   one; `comment-audit` doesn't need one (it's already self-contained on
   scope and triggering).
2. **`body.md`** -- the skill's own vendor-neutral mechanics: the *how*,
   once the gate (if any) says this is allowed to run.
3. **`glue.md`** (decision-log only) -- the adrpy-specific instantiation:
   which `adrpy` commands to actually run, and when. This is
   [`doc/decision-log-workflow.md`](../decision-log-workflow.md), reused
   verbatim -- it already only references `adrpy log`, `doc/decision-log/`,
   and `doc/adr/`, adrpy's own fixed paths on every repository it
   initializes, so it needs no per-project rewriting.

## Delivery differs by provider, not by skill

Each provider gets that same content, shaped to match how it actually
loads instructions:

| Provider | Mode | Where it lives |
|---|---|---|
| `claude` | Full body, inline | `.claude/skills/<name>/SKILL.md` (project) or `~/.claude/skills/<name>/SKILL.md` (global) |
| `cursor` | Full body, inline | `.cursor/rules/<name>.mdc` |
| `copilot` | Short stub + shared doc | `.github/instructions/<name>.instructions.md` |
| `agentsmd` | Short stub + shared doc, inside a marked block | `AGENTS.md` |

Claude Code and Cursor both support on-demand/agent-requested skill
inclusion, so they receive the full content inline. Copilot and a generic
`AGENTS.md` are always-loaded by their own tooling, so a full skill body
inline would bloat every request -- instead they get a short stub pointing
at one shared, tool-agnostic copy written once per skill, at
`doc/ai-skills/<name>.md` in the target repository.

Only `claude` has a meaningful global scope (`--target global`, writing
under your own home directory instead of the repository); every other
provider only understands project scope, and rejects `--target global`
with `usage-error`.

## Drift protection, not blind overwrite

Every file or `AGENTS.md` block `adrpy-skills` writes carries a leading
`<!-- adrpy-skills: v... sha256:... -->` marker -- right after the
frontmatter block for `claude`/`cursor`/`copilot`, or at the very start of
each skill's own `AGENTS.md` block. A later `install` or `remove` call
checks that marker before touching the file again:

- **foreign** -- something already exists there with no marker at all (a
  naming collision, or a file you wrote by hand). Left untouched.
- **drifted** -- a marker exists, but the file's own current content no
  longer hashes to what it recorded (you edited it since it was
  generated). Left untouched.
- **malformed** (`agentsmd` only) -- a skill's own `start`/`end` block is
  truncated (missing its closing tag) or duplicated (more than one
  complete block for the same skill). Left untouched, same as `foreign`.
- **clean** -- the file still matches exactly what was last generated.
  Freely overwritten -- this is what makes a routine `pip install
  --upgrade adrpy-ai` followed by a re-run actually pick up an update.

`foreign`, `drifted`, and `malformed` all require `--force` to overwrite
(`install`) or delete (`remove`) -- including the one shared
`doc/ai-skills/<name>.md` file itself, and every code path `remove` uses
to delete something (a full file, an `AGENTS.md` block, the shared doc).
`remove` never deletes `AGENTS.md` itself, even when stripping its only
remaining skill block would leave it empty -- that's a judgment call for
you, not this command.

## Known limitation: no cross-process lock on `AGENTS.md`

Unlike `adrpy`'s own repository-wide lock (ADR001V01), `adrpy-skills`
does not lock `AGENTS.md` (or any other file it writes) against a second,
truly concurrent `adrpy-skills` invocation. Two processes racing to
install different skills into the same `AGENTS.md` at the same instant
could, in principle, both read the file before either writes it back,
losing one of the two updates. Measured risk in this tool's actual usage
pattern (a one-off installer invocation, not a long-running service) is
very low -- real, staggered process launches did not reproduce the race,
only an artificially widened window did -- so this is accepted as a known
limitation rather than fixed with a lock. If you script concurrent
`adrpy-skills` calls against the same target (e.g. from CI), serialize
them yourself.

## Commands

| Command | Purpose |
|---|---|
| [`help`](help.md) | Lists every `adrpy-skills` command, or describes one of them in full. |
| [`install`](install.md) | Installs one or more bundled skills for one or more providers. |
| [`remove`](remove.md) | Removes one or more bundled skills for one or more providers. |
| [`list`](list.md) | Reports what's installed where, and whether any of it has drifted. |

Every failure code a command can return is documented on that command's
own page, in its `## Failure codes` table -- the same structured
`failure_codes` field `adrpy-skills help <command>` returns at runtime.
If a page here and the CLI ever disagree, the CLI is right and the page
has drifted.
