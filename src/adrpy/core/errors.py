"""Structured, reported command failures, and CLI usage errors -- kept as
two distinct exception types because they map to two different fixed exit
codes: an operation that was attempted and refused vs. a malformed
invocation of the command itself (unknown flag, missing value)."""


class CommandError(Exception):
    def __init__(self, code, detail=None, data=None, warnings=None):
        """`data`: a structured payload for a failure that isn't fully
        explained by `code` alone -- e.g. not-latest-version needs to
        name WHICH version actually is the latest, which a fixed code
        string can't carry and `detail` (stderr-only free text) isn't
        part of the JSON contract.

        `warnings`: a real side effect (an encoding repair, an
        orphan-temp-file cleanup, a stale-lock reclaim, a retried write)
        can already have happened before this
        same command run goes on to fail for an unrelated reason -- e.g.
        `reject` can finish rewriting the target file's own status
        before discovering its predecessor is missing. Without this, that
        warning was silently dropped the moment the run ended in failure
        instead of success, even though the side effect was real."""
        super().__init__(detail or code)
        self.code = code
        self.detail = detail
        self.data = data
        self.warnings = warnings


class UsageError(Exception):
    pass


class FailureCodes:
    """Every failure code this project can raise via CommandError, as a class
    attribute -- one canonical place to check completeness (every code appears in
    at least one command's own describe() text) against, instead of re-auditing the
    scattered literals by hand (ADR005V01). Grouped by the module that owns/raises
    each code, in that module's own raise order -- not alphabetized, so each group
    stays reviewable against the file it replaces. A code shared verbatim across 2+
    CLI commands (the exact drift risk this class exists to close) gets its own
    "Shared" group instead of being silently attributed to whichever command
    happens to be listed first. The attribute NAME is free to be anything; the
    STRING VALUE is the real, load-bearing wire code and must never change once
    assigned here -- every existing CLI/test assertion checks this exact string."""

    # Shared verbatim across 2+ CLI commands -- the confirmed drift risk this class exists to close.
    ALREADY_SUPERSEDED = "already-superseded"
    FAMILY_MEMBER_SUPERSEDED = "family-member-superseded"
    NOT_PROPOSED = "not-proposed"
    UNEXPECTED_STATUS = "unexpected-status"
    FAMILY_MEMBER_PENDING = "family-member-pending"
    FILE_ALREADY_EXISTS = "file-already-exists"
    STILL_PROPOSED = "still-proposed"
    ALREADY_REJECTED = "already-rejected"
    ALREADY_ACCEPTED = "already-accepted"
    CONFIG_FILE_NOT_FOUND = "config-file-not-found"
    FAMILY_NOT_FOUND = "family-not-found"
    FIELD_NOT_A_BOOLEAN = "field-not-a-boolean"
    FIELD_NOT_AN_INTEGER = "field-not-an-integer"
    NOT_LATEST_VERSION = "not-latest-version"

    # src/adrpy/core/warnings.py
    IO_ERROR = "io-error"

    # src/adrpy/core/naming.py
    TITLE_PRODUCES_UNRECOGNIZABLE_FILENAME = "title-produces-unrecognizable-filename"

    # src/adrpy/core/security.py
    PATH_INVALID = "path-invalid"
    PATH_OUTSIDE_REPOSITORY = "path-outside-repository"
    FIELD_IS_BLANK = "field-is-blank"
    FIELD_CONTAINS_FORBIDDEN_CHARACTER = "field-contains-forbidden-character"

    # src/adrpy/core/config.py
    LANGUAGE_NOT_SUPPORTED = "language-not-supported"
    CONFIG_FILE_TOO_LARGE = "config-file-too-large"
    CONFIG_INVALID_ENCODING = "config-invalid-encoding"
    CONFIG_INVALID_JSON = "config-invalid-json"
    CONFIG_MISSING_FIELD = "config-missing-field"
    CONFIG_UNEXPECTED_FIELD = "config-unexpected-field"
    CONFIG_WRONG_TYPE = "config-wrong-type"
    CONFIG_LENSEQ_TOO_SMALL = "config-lenseq-too-small"
    CONFIG_LENSEQ_TOO_LARGE = "config-lenseq-too-large"
    CONFIG_LENVERSION_TOO_SMALL = "config-lenversion-too-small"
    CONFIG_LENVERSION_TOO_LARGE = "config-lenversion-too-large"
    CONFIG_LENREVISION_NEGATIVE = "config-lenrevision-negative"
    CONFIG_LENREVISION_TOO_LARGE = "config-lenrevision-too-large"
    CONFIG_SEPARATOR_INVALID = "config-separator-invalid"
    CONFIG_CASETRANSFORM_INVALID = "config-casetransform-invalid"
    CONFIG_FIELD_EMPTY = "config-field-empty"
    CONFIG_PREFIX_INVALID = "config-prefix-invalid"
    CONFIG_FOLDERADR_TOO_LONG = "config-folderadr-too-long"
    CONFIG_FOLDERADR_NOT_RELATIVE = "config-folderadr-not-relative"
    # ADR007V01: folderlog, the first optional-with-computed-default field
    # in this schema.
    CONFIG_FOLDERLOG_TOO_LONG = "config-folderlog-too-long"
    CONFIG_FOLDERLOG_NOT_RELATIVE = "config-folderlog-not-relative"
    CONFIG_FOLDERADR_FOLDERLOG_OVERLAP = "config-folderadr-folderlog-overlap"
    CONFIG_TEMPLATE_TOO_LONG = "config-template-too-long"
    CONFIG_HEADERDISCLAIMER_TOO_LONG = "config-headerdisclaimer-too-long"
    CONFIG_FIELD_IS_BLANK = "config-field-is-blank"
    CONFIG_FIELD_CONTAINS_FORBIDDEN_CHARACTER = "config-field-contains-forbidden-character"
    CONFIG_MIGRATIONPATTERN_INVALID = "config-migrationpattern-invalid"
    CONFIG_HEADERTITLEFILE_TOO_LONG = "config-headertitlefile-too-long"
    CONFIG_HEADERVERSION_TOO_LONG = "config-headerversion-too-long"
    CONFIG_HEADERREVISION_TOO_LONG = "config-headerrevision-too-long"
    CONFIG_HEADERSCOPE_TOO_LONG = "config-headerscope-too-long"
    CONFIG_HEADERDOMAIN_TOO_LONG = "config-headerdomain-too-long"
    CONFIG_HEADERTITLESTATUSCREATED_TOO_LONG = "config-headertitlestatuscreated-too-long"
    CONFIG_HEADERTITLESTATUSCHANGED_TOO_LONG = "config-headertitlestatuschanged-too-long"
    CONFIG_HEADERTITLESTATUSSUPERSEDED_TOO_LONG = "config-headertitlestatussuperseded-too-long"
    CONFIG_HEADERTABLEFIELDS_TOO_LONG = "config-headertablefields-too-long"
    CONFIG_HEADERTABLEVALUES_TOO_LONG = "config-headertablevalues-too-long"
    CONFIG_HEADERMIGRATED_TOO_LONG = "config-headermigrated-too-long"
    CONFIG_STATUSNEW_TOO_LONG = "config-statusnew-too-long"
    CONFIG_STATUSACC_TOO_LONG = "config-statusacc-too-long"
    CONFIG_STATUSREJ_TOO_LONG = "config-statusrej-too-long"
    CONFIG_STATUSSUP_TOO_LONG = "config-statussup-too-long"

    # src/adrpy/core/lock.py
    REPOSITORY_LOCKED = "repository-locked"
    LOCK_LOST = "lock-lost"

    # src/adrpy/core/lifecycle.py
    REFDATE_INVALID_FORMAT = "refdate-invalid-format"
    REFDATE_IN_FUTURE = "refdate-in-future"
    REFDATE_BEFORE_HISTORY = "refdate-before-history"
    FOLDERADR_CHANGE_SCAN_INCOMPLETE = "folderadr-change-scan-incomplete"
    FOLDERADR_CHANGE_BLOCKED_BY_EXISTING_DECISIONS = "folderadr-change-blocked-by-existing-decisions"
    FOLDERADR_CHANGE_WOULD_ADOPT_UNRELATED_FILES = "folderadr-change-would-adopt-unrelated-files"
    STATUS_OR_SEPARATOR_CHANGE_SCAN_INCOMPLETE = "status-or-separator-change-scan-incomplete"
    STATUS_OR_SEPARATOR_CHANGE_BLOCKED_BY_EXISTING_DECISIONS = "status-or-separator-change-blocked-by-existing-decisions"
    SEPARATOR_CHANGE_WOULD_ADOPT_UNRELATED_FILES = "separator-change-would-adopt-unrelated-files"
    FOLDERADR_CHANGED_AFTER_LOCK_ACQUIRED = "folderadr-changed-after-lock-acquired"
    FILE_NOT_FOUND = "file-not-found"
    CANNOT_DETERMINE_ROOT_PATH = "cannot-determine-root-path"
    TARGET_DIRECTORY_NOT_FOUND = "target-directory-not-found"
    CONFIG_NOT_FOUND = "config-not-found"
    FILENAME_NOT_RECOGNIZED = "filename-not-recognized"
    FAMILY_SCAN_UNRELIABLE_ENCODING = "family-scan-unreliable-encoding"
    HEADER_INVALID = "header-invalid"
    FAMILY_SCAN_INCOMPLETE = "family-scan-incomplete"

    # src/adrpy/core/header.py
    ADR_FILE_EMPTY = "adr-file-empty"
    ADR_FILE_TOO_SHORT = "adr-file-too-short"
    ADR_HEADER_COMMENT_NOT_FOUND = "adr-header-comment-not-found"
    ADR_HEADER_INVALID_FORMAT = "adr-header-invalid-format"
    ADR_HEADER_TITLE_NOT_FOUND = "adr-header-title-not-found"
    ADR_HEADER_VERSION_NOT_FOUND = "adr-header-version-not-found"
    ADR_HEADER_REVISION_NOT_FOUND = "adr-header-revision-not-found"
    ADR_HEADER_SCOPE_NOT_FOUND = "adr-header-scope-not-found"
    ADR_HEADER_DOMAIN_NOT_FOUND = "adr-header-domain-not-found"
    ADR_HEADER_STATUS_CREATED_NOT_FOUND = "adr-header-status-created-not-found"
    ADR_HEADER_STATUS_UPDATED_NOT_FOUND = "adr-header-status-updated-not-found"
    ADR_HEADER_STATUS_SUPERSEDED_NOT_FOUND = "adr-header-status-superseded-not-found"
    ADR_STATUS_SUPERSEDE_FORMAT_INVALID = "adr-status-supersede-format-invalid"
    STATUS_LINE_FORMAT_INVALID = "status-line-format-invalid"
    STATUS_LINE_UNKNOWN_STATUS = "status-line-unknown-status"
    STATUS_LINE_DATE_INVALID = "status-line-date-invalid"

    # src/adrpy/core/decision_log.py
    LOG_CLASSIFICATION_INVALID = "log-classification-invalid"
    LOG_SLUG_INVALID = "log-slug-invalid"
    LOG_SCOPE_INVALID = "log-scope-invalid"
    LOG_SEVERITY_INVALID = "log-severity-invalid"
    LOG_RESOLUTION_INVALID = "log-resolution-invalid"
    LOG_ROUND_INVALID = "log-round-invalid"
    LOG_ROUND_TOO_LOW = "log-round-too-low"
    LOG_DIRECTORY_CONTAINS_UNRECOGNIZED_FILE = "log-directory-contains-unrecognized-file"
    # ADR007V01: folderlog is now recursively scanned, gaining the same
    # fail-closed-on-unreadable-subdirectory handling folderadr's own scan
    # already had.
    LOG_SCAN_INCOMPLETE = "log-scan-incomplete"
    FOLDERLOG_CHANGE_BLOCKED_BY_EXISTING_ENTRIES = "folderlog-change-blocked-by-existing-entries"
    FOLDERLOG_CHANGE_WOULD_ADOPT_UNRELATED_FILES = "folderlog-change-would-adopt-unrelated-files"

    # src/adrpy/cli/reject.py
    SUPERSEDED_PREDECESSOR_NOT_FOUND = "superseded-predecessor-not-found"
    REJECT_PREDECESSOR_WRITE_FAILED = "reject-predecessor-write-failed"

    # src/adrpy/cli/supersede.py
    SUPERSEDE_WRITE_FAILED = "supersede-write-failed"
    SUPERSEDE_SUCCESSOR_WRITE_FAILED = "supersede-successor-write-failed"
    SUPERSEDE_SUCCESSOR_SCAN_INCOMPLETE = "supersede-successor-scan-incomplete"

    # src/adrpy/cli/version.py
    LENVERSION_TOO_SMALL_FOR_NEW_VERSION = "lenversion-too-small-for-new-version"

    # src/adrpy/cli/revise.py
    REVISION_NOT_CONFIGURED = "revision-not-configured"
    LENREVISION_TOO_SMALL_FOR_NEW_REVISION = "lenrevision-too-small-for-new-revision"

    # src/adrpy/cli/migrate.py
    MIGRATION_PATTERN_NOT_CONFIGURED = "migration-pattern-not-configured"
    MIGRATION_SCAN_FAILED = "migration-scan-failed"
    MIGRATION_SCAN_INCOMPLETE = "migration-scan-incomplete"
    NO_DECISIONS_FOUND = "no-decisions-found"
    MIGRATION_SCAN_UNRELIABLE_ENCODING = "migration-scan-unreliable-encoding"
    ALREADY_TOOL_CREATED_ADRS_EXIST = "already-tool-created-adrs-exist"
    NO_ELIGIBLE_FILES_TO_MIGRATE = "no-eligible-files-to-migrate"
    MIGRATION_LOCK_LOST = "migration-lock-lost"
    MIGRATION_WRITE_FAILED = "migration-write-failed"

    # src/adrpy/cli/new.py
    TITLE_ALREADY_EXISTS = "title-already-exists"
    NEW_SCAN_INCOMPLETE = "new-scan-incomplete"

    # src/adrpy/cli/init.py
    CONFIG_ALREADY_EXISTS = "config-already-exists"
    LENSEQ_TOO_SMALL_FOR_EXISTING_DECISIONS = "lenseq-too-small-for-existing-decisions"
    LENVERSION_TOO_SMALL_FOR_EXISTING_DECISIONS = "lenversion-too-small-for-existing-decisions"
    LENREVISION_TOO_SMALL_FOR_EXISTING_DECISIONS = "lenrevision-too-small-for-existing-decisions"
    INIT_EXISTING_NUMBERS_SCAN_INCOMPLETE = "init-existing-numbers-scan-incomplete"

    # src/adrpy/cli/log.py
    LOG_ENTRY_ALREADY_EXISTS = "log-entry-already-exists"
    LOG_INDEX_REGENERATION_FAILED = "log-index-regeneration-failed"

    # src/adrpy/cli/help.py
    UNKNOWN_COMMAND = "unknown-command"
