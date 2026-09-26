<!-- Do not remove this comment, lines and table (1-12) -->
|Adr-Plus Fields|Values|
|--|--|
|File title md|adrpy-skills ships an adrpy skill that makes an AI agent use the CLI instead of editing ADR files by hand|
|Version|01|
|Revision|01|
|Scope|packaging|
|Domain|tooling|
|Created|Proposed (2026-09-25) <!-- Proposed -->|
|Changed|Accepted (2026-09-25) <!-- Accepted -->|
|Superseded||
<!-- Do not remove this comment, lines and table (1-12) -->
---
# adrpy-skills ships an adrpy skill that makes an AI agent use the CLI instead of editing ADR files by hand

## Deciders

* Deciders: Fernando Cerqueira (repo owner), decided during the Round 44 hardening round.

Revision 01 (Round 46) keeps the decision and updates this record with what real-agent runs showed after it was written: see "Validation" under Consequences and the note on where protections live.

Technical Story: Round 44 ran a fresh `claude -p` agent in scratch repositories with only what `adrpy-skills` installs (the global `CLAUDE.md` swapped for a placeholder). In scenario S3 the agent renamed a successor with `git mv`, dropped its `--001` suffix -- which silently broke the supersede link -- and told the user the suffix was "a revision". Nothing it had installed said that the `adrpy` CLI exists, that `adrpy check` comes first, or that decision files are never renamed.

## Context and Problem Statement

[ADR009V01](ADR009V01-ai-coding-agent-skills-installer-ships-as-a-separate-adrpy-skills-entry-point-with-per-provider-full-body-or-stub-delivery.md) decided how `adrpy-skills` delivers skills to each provider; the skills it shipped (`decision-log`, `pre-release-audit`) carry judgment -- when to record a decision, when to run a review -- not how to operate on the decision files. An adopter's agent therefore meets an `adr-config.adrplus` repository knowing only that ADRs are Markdown files, and edits them the way it edits any Markdown: renaming, hand-writing headers, deleting suffixes. The CLI's own safeguards (validation before every action, hints naming the literal repair) only help an agent that runs it. The package's README and `doc/` do not travel into the adopter's repository.

How should an adopter's AI agent learn that this repository's decisions are managed by `adrpy`, and how to change them?

## Decision Drivers

* The failure seen in S3 was not a bad command but no command: the agent never ran `adrpy` at all.
* The guidance has to be present in the adopter's repository or agent configuration -- the package's own README is not.
* It must trigger on any ADR task in an adrpy repository, not only when a decision is being recorded (the `decision-log` skill's trigger).
* "Whether and when to record" is already the `decision-log` skill's judgment; the new text must not duplicate or override that gate.
* It is natural-language guidance for an LLM, so, as ADR009 records, its reliability can only be confirmed by a real-agent run, not by unit tests.

## Considered Options

* Rely on the CLI alone: better hints and `adrpy <command> --help`.
* Put the rules in the shipped `decision-log` skill.
* A separate shipped `adrpy` skill, triggered by an `adr-config.adrplus` at the repository root, that says how to change decision files and defers "whether" to `decision-log`.

## Decision Outcome

Chosen option: "A separate shipped `adrpy` skill", because it is the only option that reaches an agent that does not yet know the CLI exists, on every ADR task, without mixing operating rules into a judgment skill.

1. `adrpy-skills` ships a third skill, `adrpy`, installed by default next to `decision-log` and `pre-release-audit` for every provider, through the same ADR009 mechanism (full body or stub plus shared doc, drift marker, `gate.md`).
2. Its `gate.md` applies it to any ADR or decision-record task in a repository that has `adr-config.adrplus`, and not otherwise (unless the user asks to set adrpy up).
3. Its body is operational: run `adrpy help` and `adrpy check --path .` first and follow each error's `hint`; never rename, hand-write or hand-edit a decision when a command does the job (the text below the header is written by hand); the `<sep><sep>NNN` suffix is the successor link and is never removed; supersede with `adrpy supersede`; repair by hand only as a hint or `data.repair` says; one command at a time; and a one-line map of every command, which a test keeps in sync with the command registry.
4. It decides nothing about whether a decision should be recorded: when `decision-log` is installed, its approval gate applies before any write.

The CLI's own texts are not a second line but the first one for anything that must hold: an agent loads only the skill its request triggers, but it always reads the output of the command it ran. In Round 46, no run of the decision-log scenario (a user's note inside the log folder) loaded the `adrpy` skill. While the `log` refusal only said it could not continue "while this file is present", the smallest model moved the note away silently; once the refusal's own text said "it is the user's file -- ask where it belongs", no model moved it in the next batch. The skill reinforces what the CLI says; a protection that matters is put in the CLI's hints, warnings and refusals too.

### Positive Consequences

* An adopter's agent is told, in its own configuration, that the CLI exists and must be used, before it touches a decision file.
* The operating rules have one home; `decision-log` stays about judgment and `adrpy` about mechanics, and `decision-log`'s gate points writes to the `adrpy` commands.
* The command map cannot silently drift from the CLI: a test fails if a registered command is missing from the skill's text.

### Negative Consequences

* One more shipped skill to keep in sync with the CLI's behavior, and one more file per provider in the adopter's repository.
* Validation (Rounds 45-46): real-agent runs (`claude -p`, only what `adrpy-skills` installs) on three Claude models over several batches. With the skill, the largest model followed its rules in every comparable run, including the S3 case that motivated it, and the intermediate one reached the same by the third batch (84%, 95%, 100%) as the skill and the CLI texts were corrected; the smallest model kept misses that more text did not close, so `doc/skills/README.md` recommends a minimum model for tasks that write decisions. These are few runs per scenario, single-turn, one provider, with verdicts reviewed by hand: evidence, not statistics.
* An agent that does not load skills at all (or a provider outside ADR009's set) is still protected only by the CLI itself.

## Pros and Cons of the Options

### Rely on the CLI alone

* Good, because there is nothing new to ship or keep in sync.
* Bad, because it does nothing for the observed failure: the agent never ran the CLI, so no hint was ever printed.

### Put the rules in the `decision-log` skill

* Good, because no new skill or provider file is needed.
* Bad, because that skill triggers on recording a decision; renaming, repairing or migrating a decision would not load it.
* Bad, because it mixes "how to operate the files" into a skill whose purpose is "whether to record", and would ship the operating rules to users who install `decision-log` without adrpy.

### A separate shipped `adrpy` skill (chosen)

* Good, because it triggers on the repository itself (`adr-config.adrplus`), for every ADR task.
* Good, because it reuses ADR009's delivery and drift protection unchanged.
* Bad, because it is one more skill to maintain, and its effect still has to be shown by a real-agent run.

## Links

* Refines [ADR009V01](ADR009V01-ai-coding-agent-skills-installer-ships-as-a-separate-adrpy-skills-entry-point-with-per-provider-full-body-or-stub-delivery.md) -- ADR009 decides how skills are delivered; this decision adds the skill that says how to operate the decision files.
* Evidence: decision-log entry `2026-09-25--audit-finding--skills--shipped-adrpy-skill-tells-agents-to-use-the-cli.md` (Round 44, S3).
