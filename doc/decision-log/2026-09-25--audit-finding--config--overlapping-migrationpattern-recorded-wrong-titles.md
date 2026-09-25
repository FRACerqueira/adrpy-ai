# A migrationpattern that reads part of a name twice recorded wrong titles; it is refused when set and by migrate, and a partial adoption finishes with a warning

**Front:** Round 46: real-agent breadth (claude -p; opus-5-5, sonnet-5, haiku-4-5; 4 batches) | **Severity:** High | **Resolution:** Escalated | **Round:** 46

In batch 1 (S10) haiku used N00:04T02 and migrate recorded titles like '01-use-rabbitmq-...' with no warning. A pattern whose T starts inside the N/V/R/P ranges, or whose ranges overlap, is now refused where it is set (config, installconfig, init seed, explore preview) and by migrate before writing, never at load. Owner decision (option A): once a decision was migrated with such a pattern the migrationpattern guard keeps it, so migrate finishes with it and warns that titles begin with part of the number; lifecycle.has_valid_header is now shared by the guard and migrate. S12 (the user asks for N00:04T02): the refusal fired in every run (0be5f3b).
