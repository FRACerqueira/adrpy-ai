# Working with adrpy

This repository's decisions are managed by the `adrpy` CLI. Every command
takes flags and prints one JSON object; none of them prompts.

## Before touching the decisions folder

1. Run `adrpy help`: it lists every command and the defaults of this
   machine.
2. Run `adrpy check --path .`. It validates the whole repository. When it
   fails, each entry in `data.errors` names the file, the rule broken and a
   `hint`. Follow the hint of each error before running any other command:
   every lifecycle command refuses a repository that does not pass check.

## Rules

- **Never rename, hand-write or hand-edit an ADR file when a command does
  the job.** Use `new`, `approve`, `reject`, `undo`, `version`, `revise`,
  `supersede` and `migrate`. They write the header, the status cells, the
  hidden status marker and the file name together; a hand edit easily
  breaks one of them. The file name and the header lines belong to the
  commands; the decision's own text below the header (the template's
  sections) is written by hand once a command has created the file.
- **The `<sep><sep>NNN` suffix is part of the name.** A file name ending
  in a doubled separator and a number (`ADR002V01-use-x--001.md` with the
  default `-`) marks the successor of decision `NNN`. Never remove or
  change it.
- **To supersede a decision**, run
  `adrpy supersede --file <path of the predecessor> --title "<new title>"`.
  It marks the predecessor Superseded and creates the successor in one
  command. Do not create the successor with `new` and link it by hand.
- **Repair by hand only when check's hint says so**, and write exactly the
  row or cell the hint gives. A failed `supersede` or `reject` that wrote
  only one file names the missing header row in `data.repair`: write that
  row as given.
- **Run one command at a time per working copy.** adrpy does not lock
  files: two commands running together on the same working copy can
  overwrite each other's work.
- Run `adrpy check --path .` again after a change or a repair.

## Commands

- `adrpy help` -- lists every command; `adrpy help <command>` describes one.
- `adrpy init --path .` -- creates `adr-config.adrplus` and the decisions folder.
- `adrpy explore --path .` -- lists every file in the decisions folder, decision or not.
- `adrpy check --path .` -- validates the repository; each error has a `hint`.
- `adrpy new --path . --title "..."` -- creates a decision, status Proposed.
- `adrpy approve --file <file>` -- marks a Proposed decision Accepted.
- `adrpy reject --file <file>` -- marks a Proposed decision Rejected.
- `adrpy undo --file <file>` -- sets an Accepted or Rejected decision back to Proposed.
- `adrpy supersede --file <file> --title "..."` -- marks an Accepted decision Superseded and creates its successor.
- `adrpy version --file <file>` -- creates a new major version of an Accepted or Rejected decision.
- `adrpy revise --file <file>` -- creates a revision (a wording fix) of an Accepted or Rejected decision.
- `adrpy migrate --path .` -- adds a header to hand-written decision files; preview with `adrpy explore --path .` first.
- `adrpy config --path .` -- reads the repository's config, or changes the fields passed.
- `adrpy installconfig` -- reads or changes this machine's default config for new repositories.
- `adrpy log --path . ...` -- writes a decision-log entry (not an ADR).

For a command's arguments and every failure code it can return, run
`adrpy <command> --help` or `adrpy help <command>`.
