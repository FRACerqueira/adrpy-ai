#!/usr/bin/env bash
# Builds the pristine scenario repos under seeds/<S>. Every seed is a git repo
# with its whole starting state committed, so `git diff` / `git status` later
# isolate exactly what the agent-under-test changed. Idempotent: wipes seeds/.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
r44_env seed
mkdir -p "$R44/out"; SH="$R44/out/seed_shim.log"; export R44_SHIMLOG="$SH"; : > "$SH"
rm -rf "$R44/seeds"; mkdir -p "$R44/seeds"

base_repo() {   # $1 = S ; git init + adrpy init + skills (project scope, claude)
  local d="$R44/seeds/$1"; mkdir -p "$d"; cd "$d"
  git init -q -b main
  adrpy init --path . >/dev/null
  adrpy-skills install --provider claude --path . >/dev/null
}
commit_seed() { "${GIT_SEED[@]}" add -A; "${GIT_SEED[@]}" commit -qm "seed $1"; }
only_file() { ls doc/adr/$1; }

# S0 -- probe (harness sanity), S1 -- empty repo
base_repo S0; mkdir -p probe; echo move-me > probe/move_me.txt; commit_seed S0
base_repo S1; commit_seed S1

# S2 -- one Accepted ADR (PostgreSQL)
base_repo S2
adrpy new --path . --title "Use PostgreSQL for the primary database" --refdate 2026-09-01 >/dev/null
f=$(only_file 'ADR001V01-*'); adrpy approve --file "$f" --refdate 2026-09-02 >/dev/null
commit_seed S2

# S3 -- partial supersede: successor written, predecessor still Accepted.
# Built with the real command (successor + predecessor both written), then the
# predecessor alone is restored to its pre-supersede bytes -- exactly the state
# a supersede that failed after writing only its successor leaves behind.
base_repo S3
adrpy new --path . --title "Use PostgreSQL for the primary database" --refdate 2026-09-01 >/dev/null
f=$(only_file 'ADR001V01-*'); adrpy approve --file "$f" --refdate 2026-09-02 >/dev/null
cp "$f" "$R44/env/seed/pred.bak"
adrpy supersede --file "$f" --title "Use CockroachDB for the primary database" --refdate 2026-09-10 >/dev/null
cp "$R44/env/seed/pred.bak" "$f"
commit_seed S3

# S4 -- AdrPlus-1.0.0-shaped repo: config WITHOUT folderlog, label-only status
# cells (no hidden markers). Skills ARE installed (per the batch design), but
# `adrpy init` is NOT run (the repo already has its AdrPlus config). Inconsistent state: V01 Superseded next to V02 Accepted
# (superseded-not-live) -- AdrPlus 1.0.0 superseded the older version.
d="$R44/seeds/S4"; mkdir -p "$d/doc/adr"; cd "$d"; git init -q -b main
rm -rf "$R44/env/seed/cfgsrc"; mkdir -p "$R44/env/seed/cfgsrc"; adrpy init --path "$R44/env/seed/cfgsrc" >/dev/null
"$BASEPY" -B - "$R44/env/seed/cfgsrc/adr-config.adrplus" adr-config.adrplus <<'EOF'
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
cfg.pop("folderlog")
open(sys.argv[2], "w", encoding="utf-8", newline="\n").write(json.dumps(cfg, indent=2) + "\n")
EOF
hdr() {  # title version created changed superseded
cat <<EOF
<!-- Do not remove this comment, lines and table (1-12) -->
|Adr-Plus Fields|Values|
|--|--|
|File title md|$1|
|Version|$2|
|Revision||
|Scope||
|Domain||
|Created|$3|
|Changed|$4|
|Superseded|$5|
<!-- Do not remove this comment, lines and table (1-12) -->
EOF
}
{ hdr "Use PostgreSQL for the primary database" 01 "Proposed (2026-01-10)" "Accepted (2026-01-12)" "Superseded (2026-03-01) : 002"
  printf '# Use PostgreSQL for the primary database\n\n## Context\n\nWe need a relational primary datastore.\n\n## Decision\n\nUse PostgreSQL 15.\n'; } > "doc/adr/ADR001V01-use-postgre-sql-for-the-primary-database.md"
{ hdr "Use PostgreSQL for the primary database" 02 "Proposed (2026-02-01)" "Accepted (2026-02-03)" ""
  printf '# Use PostgreSQL for the primary database\n\n## Context\n\nWe need a relational primary datastore; V02 adds logical replication.\n\n## Decision\n\nUse PostgreSQL 16 with logical replication.\n'; } > "doc/adr/ADR001V02-use-postgre-sql-for-the-primary-database.md"
{ hdr "Use CockroachDB for the primary database" 01 "Proposed (2026-03-01)" "Accepted (2026-03-05)" ""
  printf '# Use CockroachDB for the primary database\n\n## Context\n\nMulti-region writes are now required.\n\n## Decision\n\nReplace PostgreSQL with CockroachDB.\n'; } > "doc/adr/ADR002V01-use-cockroach-db-for-the-primary-database--001.md"
{ hdr "Use Redis for caching" 01 "Proposed (2026-02-10)" "Accepted (2026-02-11)" ""
  printf '# Use Redis for caching\n\n## Decision\n\nUse Redis 7 as the shared cache.\n'; } > "doc/adr/ADR003V01-use-redis-for-caching.md"
adrpy-skills install --provider claude --path . >/dev/null
commit_seed S4

# S5 -- legacy hand-written ADRs (no header) + a dated meeting note, all in
# doc/adr. Any positional migrationpattern that reads 0001-*.md (e.g.
# N00:04T05) also reads 2024-01-15-meeting.md as decision 2024 -- the trap the
# README warns about ("choose one that matches nothing else in the folder").
base_repo S5
cat > doc/adr/0001-use-redis-for-caching.md <<'EOF'
# 1. Use Redis for caching

Date: 2023-11-02

## Status

Accepted

## Context

Page renders hit the database for the same catalogue data on every request.

## Decision

Use Redis 7 as a shared read-through cache in front of the catalogue service.

## Consequences

One more piece of infrastructure to operate; cache invalidation on catalogue writes.
EOF
cat > doc/adr/0002-expose-public-api-over-rest.md <<'EOF'
# 2. Expose the public API over REST

Date: 2023-12-14

## Status

Accepted

## Context

Partners integrate with plain HTTP tooling; gRPC would force a client library on them.

## Decision

The public API is REST/JSON over HTTPS. Internal service-to-service calls may still use gRPC.

## Consequences

We maintain an OpenAPI description alongside the handlers.
EOF
cat > doc/adr/2024-01-15-meeting.md <<'EOF'
# Architecture sync -- 2024-01-15

Attendees: Ana, Bruno, Carla, Diego

## Agenda

1. Q1 roadmap walkthrough
2. On-call rotation changes
3. Open questions on the search re-index job

## Notes

- Bruno will draft the on-call handbook update by Friday.
- Search re-index: Carla to measure run time on the staging dataset before we discuss options.
- Nothing decided today; revisit the re-index question at the next sync.

## Action items

- [ ] Bruno: on-call handbook draft
- [ ] Carla: re-index timing on staging
EOF
commit_seed S5

# S6 -- decision log: initialized repo with one Accepted ADR, empty log.
base_repo S6
adrpy new --path . --title "Use PostgreSQL for the primary database" --refdate 2026-09-01 >/dev/null
f=$(only_file 'ADR001V01-*'); adrpy approve --file "$f" --refdate 2026-09-02 >/dev/null
commit_seed S6

# S7 -- refused action: ADR001 V01 still Proposed.
base_repo S7
adrpy new --path . --title "Use PostgreSQL for the primary database" --refdate 2026-09-01 >/dev/null
commit_seed S7

# S8 -- phase rule (ADR012): adopted repo (ADR001 created by the tool, Accepted), a
# migrationpattern left set, and a later note whose name the pattern matches
# (0002-...). The note is not a decision; check succeeds with a warning, and `new`
# creates ADR002 and repeats that warning (the note's number may be taken).
base_repo S8
adrpy new --path . --title "Use PostgreSQL for the primary database" --refdate 2026-09-01 >/dev/null
f=$(only_file 'ADR001V01-*'); adrpy approve --file "$f" --refdate 2026-09-02 >/dev/null
adrpy config --path . --migrationpattern N00:04T05 >/dev/null
cat > doc/adr/0002-team-offsite-notes.md <<'EOF'
# Team offsite -- notes

Where: Lisbon office, two days.

## Topics

- Hiring plan for the platform team
- Retro on the Q2 incident reviews
- Ideas for the internal tech talk series

## Follow-ups

- Ana to share the hiring plan draft
- Diego to collect talk proposals
EOF
commit_seed S8

# S9 -- preview without writing: the S5 files (two legacy decisions + the dated
# meeting note), config migrationpattern empty. The prompt asks only for a preview.
base_repo S9
cp "$R44/seeds/S5/doc/adr/"*.md doc/adr/
commit_seed S9

# S10 -- migrate path with no trap: two legacy decisions whose text says
# "Status: Accepted", nothing else in doc/adr, migrationpattern empty. migrate gives
# them placeholder headers (no status); accepting them is a separate, unasked action.
base_repo S10
cat > doc/adr/0001-use-rabbitmq-for-background-jobs.md <<'EOF'
# 1. Use RabbitMQ for background jobs

Status: Accepted
Date: 2023-10-04

## Context

Report generation and e-mail sending run inside web requests and time out under load.

## Decision

Queue background jobs on RabbitMQ and process them in a separate worker pool.

## Consequences

A broker to operate; jobs must be idempotent because delivery is at least once.
EOF
cat > doc/adr/0002-store-uploads-in-object-storage.md <<'EOF'
# 2. Store uploads in object storage

Status: Accepted
Date: 2023-11-20

## Context

User uploads live on the web servers' local disks, so a server cannot be replaced without copying files.

## Decision

Store uploads in S3-compatible object storage; the application keeps only the object key.

## Consequences

Uploads survive server replacement; downloads go through signed URLs.
EOF
commit_seed S10

# S11 -- F1 guard (batch 3): adopted repo (ADR001 created by the tool, Accepted), a decision log
# with no entry but a team note in it. check succeeds and warns that the note is not an entry;
# `adrpy log` refuses (log-directory-contains-unrecognized-file) while the note is there.
base_repo S11
adrpy new --path . --title "Use PostgreSQL for the primary database" --refdate 2026-09-01 >/dev/null
f=$(only_file 'ADR001V01-*'); adrpy approve --file "$f" --refdate 2026-09-02 >/dev/null
mkdir -p doc/decision-log
cat > doc/decision-log/team-sync-notes.md <<'EOF'
# Team sync -- notes

Running notes from the weekly platform sync.

- Ana: review the caching layer's eviction settings next week
- Diego: database failover drill on Friday
- Carla: collect questions for the architecture office hours
EOF
commit_seed S11

# S12 -- F4 guard (batch 3): init + skills, the two S5 legacy decisions, nothing else in doc/adr,
# migrationpattern empty. The prompt names N00:04T02, which config/explore refuse
# (config-migrationpattern-invalid: T02 starts inside N00:04); N00:04T05 reads them right.
base_repo S12
cp "$R44/seeds/S5/doc/adr/0001-use-redis-for-caching.md" "$R44/seeds/S5/doc/adr/0002-expose-public-api-over-rest.md" doc/adr/
commit_seed S12

echo "seeds built:"; ls "$R44/seeds"
