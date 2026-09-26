# installer.py's exists()-then-read TOCTOU collapsed into _read_text itself (9 sites)

**Front:** Round 37: stability front | **Severity:** Medium | **Resolution:** Direct | **Round:** 37

The stability front found list_installed() (Low-Medium) and _other_stub_providers_reference (Medium -- could crash remove() after a partial removal had already happened, hiding it) both check path.exists() and then read, raising FileNotFoundError if the file vanishes in between. The same shape appeared 9 times in installer.py; instead of patching the 2 named sites, _read_text now returns None on FileNotFoundError and every separate exists() guard was removed (d165154). Every consumer already treated None/empty as 'absent', confirmed by reading each before the change and by the unchanged 106-test skills suite. The one pure existence check with no subsequent read was left as is. New tests simulate a file vanishing exactly at the read.

Architectural review (Round 43): the fix stands under the single-owner model (ADR001): a file can still vanish between two steps for reasons other than a concurrent command (the user, an editor, git). installer.py's `_read_text` now reads through `core/fs.py`'s bounded read.
