# installconfig --seed's schema validation had zero test coverage

**Front:** Test-Adequacy | **Severity:** Low | **Resolution:** Direct | **Round:** 11

`installconfig.py`'s `--seed` path validates (`parse_repo_config(seed_text)`) before writing, but no test constructed a `--seed` file that exists and is readable yet fails schema validation. Mutation-confirmed the gap: removing that validation call left every test in `tests/test_installconfig.py`, and the full suite, green. Real risk: a future refactor reordering or accidentally dropping that line would silently corrupt the install-level config, which then fails every future `init`/`migrate` call on that machine (a deferred, confusing failure mode) rather than failing loudly at the point of the bad `--seed`.

**Fix:** new test constructing a schema-invalid `--seed` file; mutation-verified red (removed the validation call, test failed, `DID NOT RAISE CommandError`) then green after restoring it. adrpy-ai `1b53975`.
