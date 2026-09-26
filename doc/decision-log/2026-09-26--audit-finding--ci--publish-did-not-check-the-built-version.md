# The publish workflow did not check the built version is the tag's, and generated a version file nothing read

**Front:** Round 47: package and publish path | **Severity:** Low | **Resolution:** Escalated | **Round:** 47

publish.yml built and uploaded whatever version hatch-vcs produced; a dirty tree or a second tag would upload a wrong or local version. A step now requires dist/adrpy_ai-<tag>-py3-none-any.whl and .tar.gz, checked here with a matching and a mismatching tag. The hatch-vcs version-file hook wrote src/adrpy/_version.py, which nothing imported (the version comes from importlib.metadata); the owner chose to remove it. A wheel built from a clean clone has no _version.py and reports its version (d3e900f).
