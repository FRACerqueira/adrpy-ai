# Working with adrpy

This repository's decisions are managed by the `adrpy` CLI. Every command
takes flags and prints one JSON object; none of them prompts.

## Before touching the decisions folder

1. Run `adrpy help`: it lists every command and the defaults of this
   machine.
2. Run `adrpy check --path .` before the first change, even if you
   already ran `explore` or `help`: `explore` lists the files, only
   `check` validates the whole repository. When it fails, each entry in
   `data.errors` names the file, the rule broken and a `hint`. Follow the
   hint of each error before running any other command:
   every lifecycle command refuses a repository that does not pass check.

## Rules

- **Never rename, hand-write or hand-edit an ADR file when a command does
  the job.** Use `new`, `approve`, `reject`, `undo`, `version`, `revise`,
  `supersede` and `migrate`. They write the header, the status cells, the
  hidden status marker and the file name together; a hand edit easily
  breaks one of them. The file name and the header lines belong to the
  commands; the decision's own text below the header (the template's
  sections) is written by hand once a command has created the file.
- **Do only the lifecycle actions the user asked for.** Creating,
  versioning, revising, superseding or migrating a decision does not
  accept it:
  leave it as the command left it. Run `approve`, `reject` or `undo` only
  when the user asks for that action, or ask first -- a decision described
  as already made, or an old document that says "Accepted", is not a
  request to accept it. A command that needs another status first (`version`
  or `revise` of a Proposed decision) is refused: tell the user and ask;
  never approve it to make the command work.
- **Write only what the user gave.** In the decision's text, fill a
  section only with what the user said; list the sections still open and
  ask, in the closing sentence below, whether the user wants to fill them
  now. A section
  with no answer keeps the template's placeholder; when you fill part of a
  line (the chosen option, say), keep the placeholder for the part the user
  did not give (its justification). Never invent options,
  drivers or consequences, and never take Deciders or dates from git or
  the environment.
- **Close with one sentence that asks for a review.** Whenever you created a
  decision or wrote or changed its text, the last sentence of your reply asks the user
  to review that text, together with the open-sections question, e.g.:
  "Context, Drivers and Consequences are still open -- want to fill them
  now? Either way, please review the decision's text before it is
  accepted." Do this even when the user asked you to accept it (then say
  "please review the decision's text" after accepting it). Offering to
  approve it is not asking for a review, and a question about the open
  sections alone is not either.
- **The `<sep><sep>NNN` suffix is part of the name.** A file name ending
  in a doubled separator and a number (`ADR002V01-use-x--001.md` with the
  default `-`) marks the successor of decision `NNN`. Never remove or
  change it.
- **To supersede a decision**, run
  `adrpy supersede --file <path of the predecessor> --title "<new title>"`.
  It marks the predecessor Superseded and creates the successor in one
  command. Do not create the successor with `new` and link it by hand.
  When the user says a decision replaces, supersedes or changes an earlier
  one, that is a supersede, not a new decision.
- **Repair by hand only when check's hint says so**, and write exactly the
  row or cell the hint gives. When the user asked to fix a failing check,
  apply the hint's first option without asking and say which one you
  applied: a repair the user asked for is not a lifecycle action you
  start. A failed `supersede` or `reject` that wrote
  only one file names the missing header row in `data.repair`: write that
  row as given.
- **`migrate` is a one-time step, when a repository adopts adrpy.** Preview
  a pattern with `adrpy explore --path . --migrationpattern <pattern>`: it
  writes nothing. Before writing anything, list in one question the files
  in the decisions folder that do not look like decisions and where you
  intend to move them; move them and migrate only after the answer. If
  every file looks like a decision, there is nothing to ask: go ahead. In
  the pattern, N is the number's start:length and T where the title starts,
  after the separator: for `0001-use-x.md`, `N00:04T05` (`T02` would start
  the title inside the number). If a pattern the user gave is refused, say
  why and ask before using another one. Migrated decisions have no status yet,
  whatever their old text says: report them as migrated, without a status
  (never describe their old status as kept or existing), and ask before
  approving any.
  `adrpy config --migrationpattern` writes the config, and `check` fails
  until `migrate` runs: if you stop, clear it with
  `adrpy config --path . --migrationpattern ""` and tell the user. Once
  the repository has a decision `migrate` did not write, a file whose name
  only matches the pattern is not a decision; check warns about it.
- **Never move, rename or delete a file adrpy did not write to get past a
  refusal**: a note in the decisions or decision-log folder is the user's.
  Report the refusal and ask where the file belongs.
- **Relay every warning** a command returns about the files you touched
  (a number shared with a file that is not a decision, say), in your reply.
- **Run one command at a time per working copy.** adrpy does not lock
  files: two commands running together on the same working copy can
  overwrite each other's work.
- Run `adrpy check --path .` again after a change or a repair.

## Commands

- `adrpy help` -- lists every command; `adrpy help <command>` describes one.
- `adrpy init --path .` -- creates `adr-config.adrplus` and the decisions folder.
- `adrpy explore --path .` -- lists every file in the decisions folder, decision or not; `--migrationpattern <pattern>` previews what a pattern reads, writing nothing.
- `adrpy check --path .` -- validates the repository; each error has a `hint`.
- `adrpy new --path . --title "..."` -- creates a decision, status Proposed.
- `adrpy approve --file <file>` -- marks a Proposed decision Accepted.
- `adrpy reject --file <file>` -- marks a Proposed decision Rejected.
- `adrpy undo --file <file>` -- sets an Accepted or Rejected decision back to Proposed.
- `adrpy supersede --file <file> --title "..."` -- marks an Accepted decision Superseded and creates its successor.
- `adrpy version --file <file>` -- creates a new major version of an Accepted or Rejected decision, or of a migrated one (a Proposed one is refused: ask, never approve it).
- `adrpy revise --file <file>` -- creates a revision (a wording fix) of an Accepted or Rejected decision.
- `adrpy migrate --path .` -- adds a header to hand-written decision files, once, at adoption; preview a pattern with `adrpy explore --path . --migrationpattern <pattern>` first.
- `adrpy config --path .` -- reads the repository's config, or changes the fields passed.
- `adrpy installconfig` -- reads or changes this machine's default config for new repositories.
- `adrpy log --path . ...` -- writes a decision-log entry (not an ADR).

For a command's arguments and every failure code it can return, run
`adrpy <command> --help` or `adrpy help <command>`.
