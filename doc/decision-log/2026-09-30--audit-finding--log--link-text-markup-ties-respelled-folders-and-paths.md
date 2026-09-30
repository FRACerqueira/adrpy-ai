# Index link text read names as markup, and a folder respelled was a change to refuse

**Front:** Decisions index and decision log (round 53 confirmation) | **Severity:** Low | **Resolution:** Direct | **Round:** 53

Both pages escaped only `\`, `[` and `]` in a link's text, so a backtick, `_`, `&amp;` or, on POSIX, `<a:b>` or `|` showed another name or lost the link: each character that starts inline markup there is escaped (checked in cmark-gfm and markdown-it, 507 cases). A lone surrogate showed as three U+FFFD, now one. The same folder spelled another way (`doc/adr/../adr`, another case, a link to it) was refused as a folder change or named as the previous folder's index: folders are compared as the file system resolves them. Log index ties are ordered by path text, the same on every system, and two warnings name a file in a subfolder by its path in the folder.
