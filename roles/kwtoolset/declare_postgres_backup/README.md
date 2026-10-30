# Declare PostgreSQL backups

Publish one owner's complete persistent target manifest and optionally reconcile
user-level timers. See [the contract, rootless setup and lifecycle](../../install_backup_node_postgres/README.md).

Inputs:

- `pgdump_declare_owner`: required stable producer id.
- `pgdump_declare_targets`: complete list, default `[]` (zero targets is valid).
- `pgdump_declare_state`: `present` (default), or `absent` on teardown.
- `pgdump_declare_reconcile`: default `true`; use `false` when batching producers.
- `pgdump_declare_legacy_script_subdirectories`: optional former script directory
  components whose cron entries can be retired once this producer enrolls.
- `pgdump_declare_user`: defaults to the shared backup user/`standard_user`.
- `pgdump_declare_directory`: defaults to the shared manifest directory. Keep it
  consistent with `pgdump_manifest_dir` consumed by the backup role.

Call this helper only for applications intentionally enrolled in backups. It
replaces only `<owner>.json`; it never removes another producer's manifest or any
dump data. Producers must remove their manifest on uninstall. Target-specific
credentials belong in protected connection references, not inline JSON values.

In `--check`, no manifest is written/removed. Immediate reconciliation receives
an in-memory proposed manifest/state, overlays that owner on existing producers,
validates the effective registry and reports timer changes. It does not require
an installed runner or a running user service manager. With reconciliation
explicitly disabled, only the producer structure/publication intention is checked.
