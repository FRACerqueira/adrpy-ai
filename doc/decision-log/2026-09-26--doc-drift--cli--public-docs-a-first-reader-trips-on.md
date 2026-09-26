# Public docs a first reader trips on: the PR flow, the CHANGELOG's framing, install and environment notes

**Front:** Round 47: public repository files | **Severity:** Low | **Resolution:** Escalated | **Round:** 47

CONTRIBUTING said to branch from main while work happens on develop; the owner chose main as the PR target, receiving only releases, with the maintainer applying accepted changes on develop. The CHANGELOG described changes from development builds and a hardening round to readers who never had them; its Changed section was folded into Added, in the present tense, and the .adrpy.lock notes were dropped. The README now says the source install needs a git clone, how to clone on Windows with long paths, not to share an environment with the unrelated ADRpy (the import folders collide on case-insensitive filesystems), shows --provider in the first adrpy-skills example, and gives the exit codes and the --version exception (d3e900f).
