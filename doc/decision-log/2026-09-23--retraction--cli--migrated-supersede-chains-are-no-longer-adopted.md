# supersede --resume no longer adopts a supersede chain brought in by migrate

Retracts the Round 38 decision (the owner's option (a)) that supersede --resume would adopt a supersede chain brought in by migrate. H2, decided by the owner in Round 41: a supersede chain is a concept this tool creates, so it must not exist before migration. migrate now refuses the whole run when a scanned file already carries a supersede suffix (migration-successor-files-exist, data.files) -- checked after already-tool-created-adrs-exist, so a managed repository is never told to rename its own successors (075cb80). Nothing was published, so no repository relied on the old behavior.

Architectural review (Round 43): the Round 38 entry this retracted was removed by the review, together with `supersede --resume` itself, so only the migrate refusal is kept here.
