# The created-by-the-tool test has three implementations with no test binding them, and a refusal does not carry the phase warning

decision_names (the adoption boundary), consistency._has_tool_created_decision and migrate's already-tool-created guard each test 'a valid header migrate did not write'; they agree today (probed by the review) but no test ties them, so a change to one can drift. Also, when a lifecycle command refuses an inconsistent repository, the phase warning is not in its response; check shows it. Left as is in Round 45 (572c5c7).
