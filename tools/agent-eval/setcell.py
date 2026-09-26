"""setcell.py FILE ROW VALUE -- hand edit of one ADR header row (used by the controls only)."""
import re
import sys

p, row, val = sys.argv[1:]
t = open(p, encoding="utf-8", newline="").read()
pat = r"(?m)^\|" + re.escape(row) + r"\|[^\r\n]*\|(?=\r?$)"
t, n = re.subn(pat, lambda m: "|" + row + "|" + val + "|", t, count=1)
assert n == 1, (p, row)
open(p, "w", encoding="utf-8", newline="").write(t)
