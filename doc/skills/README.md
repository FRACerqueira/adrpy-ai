<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← README](../../README.md) · [Command Reference](../commands/INDEX.md) · [Decision-log workflow](../decision-log-workflow.md)

# `adrpy-skills`: installing the judgment layer

`adrpy` manages the ADR/decision-log *record* -- it never decides when a
decision needs recording, when a hardening review is due, or when to close
a review cycle. That judgment ships as two vendor-neutral AI coding-agent
skills (`decision-log`, `pre-release-audit`).
A third skill, `adrpy`, tells an agent how to drive the CLI itself: run
`adrpy help` and `adrpy check` first, follow each error's hint, and change
decision files only through the commands, never by hand.
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
   global instructions. Every bundled skill has one: `pre-release-audit`
   and `decision-log` say when they may run, and `adrpy`'s says it applies
   to ADR tasks in a repository that has `adr-config.adrplus`.
2. **`body.md`** -- the skill's own vendor-neutral mechanics: the *how*,
   once the gate (if any) says this is allowed to run.
3. **`glue.md`** (decision-log only) -- the adrpy-specific instantiation:
   which `adrpy` commands to actually run, and when. This is
   [`doc/decision-log-workflow.md`](../decision-log-workflow.md), reused
   verbatim. It names the folders by their config fields (`folderadr`,
   `folderlog`), with `doc/adr/` and `doc/decision-log/` only as the
   defaults, and says to read the repository's own values with
   `adrpy config --path .`, so it needs no per-project rewriting.

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

## Which model to use

The skills are instructions in natural language: how well an agent follows
them depends on the model, not only on the text. They were tested with
Claude Code (`claude -p`, one fresh session per scenario, only what
`adrpy-skills` installs), with three models, in four batches; after each
batch the skills and the CLI were corrected from what it showed. Batches
1 to 3 ran the same scenarios; batch 3 added two (a note left in the
decision-log folder, and a user who names a `migrationpattern` that reads
part of the number), and batch 4 re-ran those two and the one with a
file to move out of the decisions folder, twice each.

Rules followed, on the scenarios batches 1 to 3 share:

| Model | Batch 1 | Batch 2 | Batch 3 |
|---|---|---|---|
| Claude Opus 5.5 | 100% | 100% | 100% |
| Claude Sonnet 5 | 84% | 95% | 100% |
| Claude Haiku 4.5 | 67% | 85% | 80% |

- **Opus** and **Sonnet**, in one of the scenarios batch 3 added (scored
  apart from the table), each once used another pattern than the one the
  user gave, after the CLI refused it, without asking first; neither did
  in batch 4. Sonnet's misses in batch 2 were small (a question it did
  not need to ask, how it described the status of migrated decisions).
- **Haiku**, after batch 1's corrections, no longer approved a decision
  to be able to version it, nor moved the file in the decisions folder
  without asking; but it kept creating a new decision where the user
  described a replacement (a supersede), not always asking for a review,
  not relaying a command's warning, saying things about the result that
  were not true, and swapping a refused pattern without asking. In batch 3 it moved the
  user's note out of the decision-log folder without asking and did not
  say so; in batch 4 no model moved it. That is credited to the refusal
  text of `adrpy log` (the file is the user's: ask where it belongs), not
  to the `adrpy` skill, which those runs did not load.

These are one or two runs per scenario, on one day, with one provider.
Each run was a single turn: what an agent does after the user answers its
question was never tested. Every verdict was reviewed by hand, because the automatic
evaluator got some wrong in every batch.

Recommendation: for any task that writes decisions, use a model at least
as capable as Claude Sonnet 5. The one read-only scenario (previewing a
`migrationpattern` with `adrpy explore`, nothing written) passed with all
three models; but in the writing scenarios Haiku left out warnings and
misreported results, so if a smaller model reports what `adrpy check` or
`adrpy explore` said, check it against the JSON. The other providers (Cursor, GitHub Copilot,
a generic `AGENTS.md`) and their models were **not** tested with a real
agent: test the scenarios that matter to you before relying on them.

## A skill that is no longer shipped

Development builds also shipped a `comment-audit` skill; it is no longer
part of adrpy. `install` refuses it, but `remove` and `list` still know
its name, so what an older version installed can be found and removed:
`remove` (with `--skill comment-audit`, or the default `all`) deletes it
under the same drift rules as any other skill, and `list` with the default
`all` shows its rows only where something of it is still on disk.

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
  truncated (missing its closing tag), duplicated (more than one
  complete block for the same skill), or crosses another skill's block
  (wraps another skill's block inside its own, or overlaps it -- only
  reachable by hand-editing,
  since `install` only ever replaces a block in place or appends). Left
  untouched, same as `foreign`; `--force` replaces only this skill's own
  tags, never the other skill's block.
- **clean** -- the file still matches exactly what was last generated.
  Freely overwritten -- this is what makes a routine `pip install
  --upgrade adrpy-ai` followed by a re-run actually pick up an update.

In `AGENTS.md`, tags indented 0-3 spaces are this tool's own syntax. Past
that (four spaces or a tab, where Markdown starts an indented code
block), a copy of a skill's tags counts as its block only when the
marker's hash still matches -- a block an editor re-indented, which
`install` updates in place, keeping the indentation. Any other indented
copy (no marker, edited since, or repeated/unpaired tags) is your own
text: never touched, even
with `--force`, and `install` appends a new block with a warning saying
why. Accepted limitation: a verbatim indented copy of the tool's block,
left alone in the file, is indistinguishable from a re-indented block
and is treated as one -- which is why `remove` deletes an indented block
only with `--force` (reason `indented`).

`foreign`, `drifted`, and `malformed` all require `--force` to overwrite
(`install`) or delete (`remove`) -- including the one shared
`doc/ai-skills/<name>.md` file itself, and every code path `remove` uses
to delete something (a full file, an `AGENTS.md` block, the shared doc).
`remove` never deletes `AGENTS.md` itself, even when stripping its only
remaining skill block would leave it empty -- that's a judgment call for
you, not this command.

One deliberate exception: before doing anything else, `install` and
`remove` delete temp files an earlier interrupted `adrpy-skills` write
left behind -- only files named exactly `<target name>.<32-hex uuid4>.tmp`,
older than 30 seconds, in the same folder as a file this call itself
would write (never a folder-wide or recursive scan). Each removal is
reported in `warnings`. No other file is ever deleted without `--force`.

The full, closed set of values `skipped[].reason` can ever take, across
both `install` and `remove`, is exactly: `foreign`, `drifted`,
`malformed` (the three drift statuses above), **`indented`** (`remove`
only, `agentsmd`: see the indentation note above), plus one more that
isn't a drift status at all -- **`shared-doc-blocked`** (`install` only): a
stub-mode provider's own file/block was skipped not because of its own
drift status, but because the one shared doc it would point at was
itself `foreign`/`drifted` and blocked. `remove` has no equivalent --
removing a stub-mode provider's own file/block never waits on the
shared doc's own removability, since deleting a pointer is safe whether
or not the thing it points at can also be cleaned up right now.

## Known limitation: the drift marker is not tamper-evident

The content-hash marker above detects accidental drift (a hand-edit since
the file was last generated) -- it is not a cryptographic signature.
Anyone who already has write access to a target file can compute their
own valid-looking marker over content of their choosing (the hash
algorithm is public and unkeyed, by design -- this is a local CLI with no
key-provisioning story). This grants no extra write/delete leverage:
`install` always regenerates content from the package's own bundled
resources rather than trusting an existing "clean" file, so a forged
marker can't make attacker content survive an `install` call. The one
real effect is on `list`, which is read-only and only hashes what's
already there: a forged marker makes `list` report `drifted: false` for
content that was never actually generated by this tool. Since the files
involved are AI-coding-agent instructions read and acted on by an agent,
treat `list`'s `drifted: false` as "matches its own recorded hash," not
as "verified authentic" -- it was never meant to defend against someone
who already has write access to your target directory or home folder.

## Links that lead outside the target

`install` and `remove` refuse, before touching anything, when a file they
would write or remove resolves -- through a junction or symlink planted
inside `--path` (or under your home directory, for `--target global`) --
to somewhere outside it, with `path-outside-repository`. Without this, a
cloned repository carrying such a link could have `remove` delete, or
`install` overwrite, a file elsewhere on your machine, and an `AGENTS.md`
that is itself a link could have its target's content copied into the
repository. If the link is intended (a dotfiles setup linking
`.claude/skills` or `~/.claude` elsewhere, say), pass
`--allow-external-links`.

## One invocation at a time

`adrpy-skills` follows the same single-owner rule as `adrpy`: it does not
lock `AGENTS.md` (or any other file it writes) against a second
`adrpy-skills` or `adrpy` invocation running at the same moment on the
same working copy. Each file is still written atomically -- a reader
sees the old file or the new one, never a partial one -- but two calls
racing on the same `AGENTS.md` could both read it before either writes it
back, and the last one to write wins. The same race can cross files: an
`install` of a stub-mode provider running while a `remove` of another one
deletes the shared doc can leave the new stub pointing at a shared doc
that is gone -- `list` then shows it (`shared-doc` not installed, the stub
installed), and re-running `install` repairs it. A `list` running while
another call writes reads each file at a different moment, so its rows
can mix before-and-after states -- re-run it once the other call
finishes. Don't run `adrpy-skills` commands in parallel on the same
working copy; if you script them (e.g. from CI), run them one after
another.

## Commands

| Command | Purpose |
|---|---|
| [`help`](help.md) | Lists every `adrpy-skills` command, or describes one of them in full. |
| [`install`](install.md) | Installs one or more bundled skills for one or more providers. |
| [`remove`](remove.md) | Removes one or more bundled skills for one or more providers. |
| [`list`](list.md) | Reports what's installed where, and whether any of it has drifted. |

Every failure code a command can return is documented on that command's
own page, in its `## Failure codes` table -- the same structured
`failure_codes` field `adrpy-skills help <command>` returns at runtime,
rendered into the page by `scripts/generate_command_docs.py` (see the
[Command Reference](../commands/INDEX.md) for how that is kept in step).
Two codes can come from any command without being listed
on its page: `unknown-command` (the verb itself isn't recognized) and
`internal-error` (an unexpected bug in the tool -- please report it).
