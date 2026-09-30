# The decisions index left out decisions it did not name, and an unreadable folder emptied it

**Front:** Resilience of the INDEX.md write path (round 51 confirmation) | **Severity:** Medium | **Resolution:** Direct | **Round:** 51

render named only invalid-header files: conflict markers, an unreadable file and a decision name with no header were left out silently, and config writes the index without validating. The second opinion on the first fix found that an unreadable decisions folder then wrote an index with no rows, naming the folder as a decision file, and that two files of one name in two subfolders were one name twice.

Fix: every decision left out is named by its path in the folder; a folder the scan could not read keeps the page as it was, with a warning naming the folder. A legacy name with no header before migrate stays silent. Red then green in tests/test_adr_index.py.
