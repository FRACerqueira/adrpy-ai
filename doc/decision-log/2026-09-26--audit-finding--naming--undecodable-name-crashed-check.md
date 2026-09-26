# A decision name holding a byte that is not UTF-8 made check and the rewriting commands fail with internal-error

**Front:** Round 49: R48 changes and the symlink target (Fable 5.1) | **Severity:** Medium | **Resolution:** Direct | **Round:** 49

A Round 48 regression: the new byte counts on existing names used str.encode('utf-8'), which raises on the lone surrogate Python gives for an undecodable byte (surrogateescape on POSIX, an unpaired UTF-16 unit on NTFS); check and approve then answered internal-error where they had worked. fs.name_bytes counts with os.fsencode (falling back to UTF-8 with surrogatepass for a surrogate not from disk), used by the rewrite limit and check's warning. Red then green on Windows and POSIX (f57d438).
