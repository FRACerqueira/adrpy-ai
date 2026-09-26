# The phase warning names each ignored file's number and says when a new decision shares it

**Front:** Round 46: real-agent breadth (claude -p; opus-5-5, sonnet-5, haiku-4-5; 4 batches) | **Severity:** Low | **Resolution:** Escalated | **Round:** 46

In S8 no model relayed a concrete collision: the phase warning named the ignored file but not its number. It now lists each ignored legacy file with the number read from its name, and after new, version, revise or supersede adds 'ADR002 now shares number 2 with 0002-...'. From batch 2, opus and sonnet relayed it in 4/4; haiku did not (0be5f3b).
