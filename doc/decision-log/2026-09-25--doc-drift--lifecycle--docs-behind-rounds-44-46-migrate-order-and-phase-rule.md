# Docs vs code after Rounds 44-46: migrate order, the one rule, the 0-byte legacy case and the folderlog warning

**Front:** Round 46: documentation audit (docs vs code, skill vs CLI, model guidance vs reports, ADRs) | **Severity:** Medium | **Resolution:** Direct | **Round:** 46

An independent audit of everything Rounds 44-46 changed found doc/lifecycle.md behind the code: the migrate order lacked the overlap refusal and the partial-adoption exemption; 'the one rule' said a number is never given to a second file, which the phase rule contradicts after adoption; the 0-byte legacy-name case claimed a re-run migrates it; the folderlog non-entry warning was not described; README said every command names an ignored file in warnings. Corrected to the code (b5649f4).
