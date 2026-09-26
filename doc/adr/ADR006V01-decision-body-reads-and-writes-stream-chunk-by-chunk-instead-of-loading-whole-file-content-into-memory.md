<!-- Do not remove this comment, lines and table (1-12) -->
|Adr-Plus Fields|Values|
|--|--|
|File title md|Decision-body reads and writes stream chunk by chunk instead of loading whole-file content into memory|
|Version|01|
|Revision||
|Scope|core/lifecycle.py, core/atomic_write.py, cli/migrate.py|
|Domain|security|
|Created|Proposed (2026-09-21) <!-- Proposed -->|
|Changed|Accepted (2026-09-21) <!-- Accepted -->|
|Superseded||
<!-- Do not remove this comment, lines and table (1-12) -->
---
# Decision-body reads and writes stream chunk by chunk instead of loading whole-file content into memory

## Deciders

* Deciders: Fernando Cerqueira (repo owner), decided while closing round 28's systematic security-audit findings.

Technical Story: round 28 (invariant "every read of file content has a real, enforced upper bound") found that `core/lifecycle.py`'s `read_lines_with_report` (the shared primary read behind `read_target`, used by every per-file mutating command: approve/reject/undo/supersede/version/revise, plus reject's own second read of a predecessor sibling) and `cli/migrate.py`'s per-candidate legacy-file read both load a decision file's entire content into memory with no size bound, live-measured at a 3x-of-file-size peak-memory multiplier (150MB file -> ~300MB traced peak). Round 26/27 had already closed the same class of bug for HEADER-only reads (`read_header_lines`, now bounded to 16KB); this is the sibling gap for reads that also need the file's BODY.

## Context and Problem Statement

A decision file's header is schema-bounded (every header field has a hard max length in `core/config.py`), so a fixed, generous byte cap safely rejects only pathological input there. A decision's BODY has no such bound -- it is free-form Markdown content, and for `migrate.py` specifically, the write is explicitly defined (see its own module docstring) as passing the source file's content through byte-for-byte, whatever its size. A fixed size cap on the body, the same shape as the header's, would therefore either reject content a real user legitimately wrote (if generous), or still leave a real, if smaller, memory-exhaustion window open (if conservative but not truly bounded).

Is there a way to close the unbounded-read/write class for the body the same way it was closed for the header -- a real, enforced bound on memory used per operation -- without capping (and therefore sometimes rejecting) legitimate content of any size?

## Decision Drivers

* A fixed byte cap on the body is a worse fit here than it was for the header: the header's own schema already bounds it, so a cap can never reject anything legitimate; the body has no such schema bound, so any fixed cap is an arbitrary, eventually-wrong number.
* `migrate.py`'s own write is already defined as a byte-for-byte pass-through with no transformation -- streaming it (read a chunk from the source, write the same chunk to the destination, repeat) is a pure mechanical change with zero behavior difference from today's whole-buffer copy.
* `approve`/`reject`/`undo`/`supersede`/`version`/`revise` all rewrite a file's body through `read_body`, which normalizes the body's line endings to this host's `os.linesep` (matching the reference tool's own behavior) -- a real transformation, not a pass-through, so streaming this path is a materially larger change than migrate's.
* Every one of these commands already writes through `core/atomic_write.py`'s temp-file-then-`os.replace` mechanism (the atomic write per file, ADR001) for crash safety -- any streaming design has to preserve that guarantee, not trade it away for a smaller memory footprint.
* This project's own established discipline (rounds 22-28) is to close a bug class structurally once a bounded fix for one instance of it is found to have a sibling with a materially different shape, rather than pattern-matching the same narrow fix onto a case it doesn't actually fit.

## Considered Options

* Do nothing differently; treat the unbounded body read/write as an accepted risk (decision-log `risk-accepted`), since a decision file's body is legitimate user content, not an obviously attacker-controlled input the way a `--seed` file or a config value is.
* Apply the same fixed-byte-cap pattern used for the header (a generous constant, refuse with a new failure code past it) to the body too, accepting that it will eventually reject some real, if unusually large, legitimate content.
* Stream both the read and the write for every path that handles a decision's body -- `migrate.py`'s pass-through copy, and `read_target`'s header-parse-then-preserve-body path (extended to also normalize line endings during the stream, replicating `read_body`'s existing semantics exactly) -- so memory use per operation stays bounded regardless of file size, with no cap and no rejection of legitimate content at all.

## Decision Outcome

Chosen option: **stream both read and write for every body-handling path**, split into two mechanically different pieces because they have different requirements:

1. **`migrate.py`**: a pure chunked copy (already zero-transformation by design) from the source file directly into the destination temp file, via a new `atomic_write_chunks(path, chunks_factory)` helper in `core/atomic_write.py` that generalizes `atomic_write_bytes`'s existing temp-file/`os.replace`/retry mechanics to accept a chunk producer instead of one pre-assembled `bytes` object.
2. **`read_target`'s body-preserving commands** (approve/reject/undo/supersede/version/revise): the header is parsed via the already-bounded `read_header_lines`/`_read_header_bytes` (16KB cap, unchanged); the exact byte offset where the body starts is found by scanning that same bounded buffer for the header-line-count-th real line terminator (no chunk-straddling risk, since the scan runs once over the whole, already-capped buffer); the body itself is streamed from that offset, chunk by chunk, through a byte-level transform that converts every real line terminator to `os.linesep` and replaces invalid UTF-8 byte sequences with U+FFFD -- reproducing `read_body(read_lines_with_report(path))`'s existing output byte-for-byte, without ever holding the whole body in memory.

This also fixes a related, smaller bug found while designing the fix: `_read_header_bytes`'s per-chunk incremental newline count (introduced in round 27) can double-count a `\r\n` pair that straddles exactly on a 4096-byte chunk boundary, since each chunk is scanned in isolation. Reachable only by a header whose real content exceeds one 4096-byte chunk (not reachable by any schema-valid header today, per round 28's own measurement of a maximally-long realistic header at ~1.2KB), but incorrect regardless of real-world reachability. Fixed by rescanning the whole accumulated buffer (still capped at 16KB total, so still O(1) relative to file size, unlike the O(n^2) pattern round 27 closed) instead of trusting a per-chunk-isolated count.

### Positive Consequences

* No decision file's body, however large, can ever exceed a small, constant per-operation memory footprint for any of the 7 commands that read one (approve/reject/undo/supersede/version/revise/migrate) -- the memory-exhaustion class this ADR exists to close is closed without exception, not narrowed to "below some fixed size."
* No legitimate content is ever rejected -- unlike a fixed cap, there is no size past which a real user's decision becomes unusable by this tool.
* Fixes a genuine (if not currently reachable by any schema-valid file) correctness bug in `_read_header_bytes`'s own newline counting as a byproduct of building the body-boundary detection this ADR needs anyway.

### Negative Consequences

* A real, non-trivial implementation cost: `read_target`'s own contract changes (it no longer returns the full body as pre-split lines; body handling moves to write time, streamed directly from the original path), and `rewrite_status_field`/`mark_superseded`'s `content` return value is no longer a fully materialized string (existing callers already discard it, confirmed by reading every call site, so this is a safe but real signature/contract narrowing).
* The byte-level line-ending-normalization-plus-invalid-UTF-8-replacement transform, implemented as a streaming pass with cross-chunk state (a pending lone `\r` carried to the next chunk; an incremental UTF-8 decoder for the encoding-repair detection), is meaningfully harder to reason about and to get byte-identical to the current whole-buffer implementation than either the header's own bounded read or migrate's pure pass-through copy -- verified via a dedicated adversarial test suite (CRLF straddling a chunk boundary, a lone CR at true end-of-file, no trailing newline at all, multiple trailing blank lines, invalid UTF-8 straddling a chunk boundary, an entirely empty body) asserting byte-identical output against the pre-refactor implementation, not just a green existing suite.
* `migrate.py`'s per-candidate source read and its temp-file write share one retry budget (the source read runs inside the chunk-producer callable, so preparing the temp file retries both together, up to 5 attempts), and committing the temp file into place has its own budget of 5 (`core/fs.py`'s `prepare_write`/`commit_write`) -- instead of the source read and the destination write each having an independent retry, as before streaming. A deliberate simplification, not an oversight, but a real behavior change under sustained contention on the source file (fewer attempts for the read than two independent budgets would give).

## Pros and Cons of the Options

### Do nothing differently (risk-accepted)

* Good, because it costs nothing now.
* Bad, because a decision file's body, while typically user-authored, is not necessarily attacker-inert: a repository can contain a file planted or corrupted by a misconfigured process, or an accidental duplicate/concatenation, and every one of the 7 body-reading commands would still pay an unbounded memory cost operating on it.

### Fixed byte cap (mirroring the header's own fix)

* Good, because it is the smallest possible change, directly reusing an already-proven pattern (`_HEADER_READ_MAX_BYTES`).
* Bad, because the body has no schema bound to size the cap against (unlike every header field) -- any fixed number is an arbitrary line that a legitimate, if unusually long, decision body will eventually cross, at which point the tool refuses to operate on the user's own real content.
* Bad, because `migrate.py`'s own documented contract is a byte-for-byte pass-through of arbitrary pre-existing content -- capping it is a functional regression for exactly the class of large legacy file migrate exists to handle.

### Stream both read and write (chosen)

* Good, because it closes the memory-exhaustion class completely, with no size past which legitimate content stops working.
* Good, because `migrate.py`'s half of this is a pure mechanical change (already zero-transformation), essentially risk-free.
* Bad, because the `read_target` half is a real, cross-cutting change to shared plumbing (used by 6 of this project's 7 body-touching commands), with correctness risk concentrated in the newline-normalization-plus-encoding-repair streaming transform -- mitigated by, but not eliminated by, a dedicated adversarial byte-identical-output test suite.

## Links

* Closes: the two round-28 (2026-09-21) `audit-finding` decision-log entries covering `read_target`/`read_lines_with_report` and `cli/migrate.py`'s own candidate read.
* Related: `doc/adr/ADR001V01-...md` (the atomic write per file this refactor must preserve), `doc/adr/ADR005V01-...md` (the other "found the same class was broader than the first fix" decision).
