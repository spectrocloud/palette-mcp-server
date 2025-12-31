# (OPTIONAL) Overrides the copywrite config schema version
# Default: 1
schema_version = 1

project {
  license          = "Apache-2.0"
  copyright_holder = "Spectro Cloud"

  # (OPTIONAL) Represents the year that the project initially began
  # Default: <the year the repo was first created>
  copyright_year = 2026

  # (OPTIONAL) A list of globs that should not have copyright or license headers .
  # Supports doublestar glob patterns for more flexibility in defining which
  # files or folders should be ignored
  # Default: []
  header_ignore = [
    "vendor/**",
    "**autogen**",
    ".venv",
  ]
}