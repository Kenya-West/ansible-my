# Declare MongoDB backups

MongoDB counterpart of `declare_postgres_backup`; see
[the contract, examples, paths and rollout](../../install_backup_node_mongodb/README.md).

Inputs follow the same naming style with `mongodump_` instead of `pgdump_`:

- `mongodump_declare_owner`: stable producer id (required).
- `mongodump_declare_targets`: complete list, default `[]` (zero is valid).
- `mongodump_declare_state`: `present` (default) / `absent` on uninstall.
- `mongodump_declare_reconcile`: `true` (default); `false` for batching producers.
- `mongodump_declare_user`: shared backup user / `standard_user`.
- `mongodump_declare_directory`: shared `mongodump_manifest_dir`; keep both aligned.
- `mongodump_declare_legacy_cron_job`: default `false`; reserved for explicitly
  enrolling the old all-endpoints MongoDB compatibility producer.

Each owner atomically replaces only its JSON manifest. Targets use `execution`,
`connection`, `dump`, `output`, optional `schedule`, and stable ids exactly as the
PostgreSQL contract. MongoDB connection sources are `container_environment`,
`config_file`, and `url_file`; output is a native archive (gzip by default), not SQL.
Credentials belong in protected references or the DB container, never inline URI
values in a manifest. The helper does not infer targets from exporter endpoints.

In `--check`, no manifest is written or removed. The proposed owner/state overlays
persisted producers during immediate reconciliation; contract and timer previews
need no installed runner, MongoDB tools, Docker or running user manager. With
reconciliation disabled, only producer structure/publication intention is checked.
