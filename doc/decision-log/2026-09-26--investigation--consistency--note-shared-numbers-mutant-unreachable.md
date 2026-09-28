# The one unsure mutant, in note_shared_numbers, cannot be reached through the CLI

Round 49's mutation testing left one survivor unclassified: note_shared_numbers with `or` turned into `and` would call warnings.index on a phase warning missing from the list and raise ValueError. Traced: its four callers (new, version, revise, supersede) add exactly that warning, computed from the same snapshot, before calling it, so the state cannot occur through the CLI. The adopted test in tests/test_behaviour_pins.py pins the helper's own contract; no code change (f57d438).
