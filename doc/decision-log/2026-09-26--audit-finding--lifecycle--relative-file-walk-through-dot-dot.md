# A relative --file with .. walked through folders that are not the file's ancestors

**Front:** Round 48: R47 boundaries (Opus 5.5 and Fable 5.1) | **Severity:** Low | **Resolution:** Escalated | **Round:** 48

Round 47 made a relative --file absolute without collapsing '..', so `--file ../B/...` from repository A could find A's config (the boundary check then refused it with a misleading target-outside-folderadr). The owner first chose resolve(); the independent pre-commit review reproduced that it let a junction inside A to B's decisions folder make a path under A approve B's decision. The owner then chose os.path.abspath: '..' collapsed, no link followed, so a link out of the repository is refused as before. Red then green for both cases (208e32a).
