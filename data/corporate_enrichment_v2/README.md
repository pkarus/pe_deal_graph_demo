# Manifest-only directory

The large generated enrichment CSVs are deliberately omitted from the GitHub copy. `MANIFEST.json` is retained because the explorer uses it in the cache fingerprint when querying the existing Snowflake data. Its presence does not mean the local CSVs exist.

Before regenerating enrichment, move this manifest-only directory aside, regenerate the original corporate careers, and follow `docs/GITHUB_HANDOFF.md`. The enrichment generator refuses an existing manifest. Do not use the loader until regeneration has produced all required files.
