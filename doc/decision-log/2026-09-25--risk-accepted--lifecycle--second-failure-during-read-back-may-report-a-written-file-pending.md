# An OSError followed by a Ctrl+C during the read-back leaves a written file reported as pending

When a commit raised an OSError after its rename and a Ctrl+C arrives during the read-back, landed_after_failure answers not confirmed: supersede then reports the written predecessor as pending, with a repair row that is not needed. The owner accepted this cost with option B for the second-interrupt case: it needs two failures in one short window, the command still ends, and check reports the real state of the disk (572c5c7).
