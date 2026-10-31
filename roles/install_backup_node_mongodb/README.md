# MongoDB backups

MongoDB counterpart of `install_backup_node_postgres`: producer-owned persistent
JSON declarations, one user-level systemd oneshot/timer per target, private
credentials, atomic dumps, retirement without deleting data, and real check-mode
previews. The generic role contains no list of database services.

## Paths and variables

The `pgdump_*` PostgreSQL settings have equivalent **`mongodump_*`** settings:

| Setting | Default |
|---|---|
| `mongodump_backup_user` | `standard_user` |
| `mongodump_backup_home` | `/home/<user>` |
| `mongodump_manifest_dir` | `~/.config/ansible-backup/mongodb.d` |
| `mongodump_runner_path` | `~/.local/lib/ansible-backup/mongodb_backup.py` |
| `mongodump_systemd_unit_path` | `~/.config/systemd/user` |
| `mongodump_backup_location_root_path` | `/etc/mongodb/db_backup` |
| `mongodump_backup_python` | `/usr/bin/python3` |
| `mongodump_backup_calendar` | `*-*-* 00:00:00 UTC` |
| `mongodump_backup_randomized_delay` | `15min` |
| `mongodump_backup_timeout` | `1h` |
| `mongodump_backup_docker_host`, `mongodump_backup_docker_context` | empty (user's Docker CLI configuration) |
| `mongodump_backup_docker_unit` | empty (no assumed docker.service) |
| `mongodump_backup_monitor_argv` | empty; analytics_node supplies the monitor wrapper |
| `mongodump_migrate_legacy` | `true` |

Shared path defaults live in `inventory/group_vars/all/0_defaults/backup_mongodb.yaml`.
The previous `mongotools_mongodb_backup_location_root_path` override is honored if
present. Docker endpoint/context selection follows the same rules as PostgreSQL:
use the backup user's configured context or explicitly select exactly one host or
context. Never guess/fallback to a different daemon. An optional user-unit
`docker_unit` dependency is explicit, not assumed for rootless Docker.

The account/Python must already exist. Apply mode enables lingering/starts the
user manager using privileged setup tasks. Manifests are `0600` in a `0700`
directory; archive directories are user-owned `0700`; new archives are `0600`.
Dump execution never runs as root. Use a home-based output root and set
`mongodump_migrate_legacy: false` to avoid privileged output ownership migration;
lingering still needs privileged setup.

## Producer contract

Call `kwtoolset/declare_mongodb_backup` from the role deploying your project,
with its complete target list, after deployment. Use `apply.tags` when called via
a tagged dynamic include, exactly as with PostgreSQL.

### Local rootless Compose database

```yaml
- name: Publish this project's MongoDB backups
  ansible.builtin.include_role:
    name: kwtoolset/declare_mongodb_backup
    apply:
      tags: [declare_backups]
  vars:
    mongodump_declare_owner: my-project
    mongodump_declare_targets:
      - id: my-project-db
        project_path: /home/example/apps/my-project
        execution:
          driver: compose_exec
          service: mongodb
          project_name: my-project  # must match actual deployment
          skip_if_unavailable: true # default; false makes stopped containers fail
        connection:
          source: container_environment
          auth_database: admin     # default
          host: 127.0.0.1:27017     # inside the DB container; default
          # database: app          # omit to dump the full instance
        dump:
          gzip: true               # default
          oplog: false             # default; replica-set full-instance dumps only
        output:
          subdirectory: my-project
          filename: dump.archive.gz
        schedule:                  # optional, same shape as PostgreSQL
          calendar: '*-*-* 00:00:00 UTC'
          randomized_delay: 15min
  tags: [declare_backups]
```

The selected database image must contain `mongodump`, `sh`, `mktemp`, and (for
`container_environment`) **`mongosh`**. This source reads
`MONGO_INITDB_ROOT_USERNAME`/`MONGO_INITDB_ROOT_PASSWORD` from inside the container.
It serializes a private temporary `mongodump --config` file with proper escaping,
then deletes it on exit. Both absent credentials mean unauthenticated access;
only one set is an error. It does not copy passwords into argv or the manifest.
For custom images, older images without mongosh, non-root backup users, TLS, or
special topology, use `config_file` or `url_file` below instead.

### Remote MongoDB / MongoDB Atlas

```yaml
mongodump_declare_owner: remote-project
mongodump_declare_targets:
  - id: remote-project-db
    execution:
      driver: direct
    connection:
      url_file: /home/example/.config/ansible-backup/mongodb-credentials/remote.uri
    dump:
      gzip: true
    output:
      subdirectory: remote-project
      filename: dump.archive.gz
```

The referenced **private regular file (`0600` or stricter)** contains a MongoDB
URI, for example `mongodb://backup:...@host:27017/?authSource=admin` or
`mongodb+srv://backup:...@cluster.example/`. Preserve percent-encoding of URI
credentials. Remote connections, authentication, DNS/SRV, TLS and server errors
remain failures; `skip_if_unavailable` applies only to local Compose containers.

For native MongoDB Database Tools YAML configuration, use instead:

```yaml
connection:
  source: config_file
  config_file: /home/example/.config/ansible-backup/mongodb-credentials/remote.yaml
```

```yaml
# Contents of remote.yaml; supported by mongodump itself (not parsed by Ansible):
uri: 'mongodb+srv://backup@cluster.example/?authSource=admin'
password: 'your-secret'
```

`config_file`/`url_file` also work with `compose_exec`: the config is streamed over
stdin into an ephemeral private container file. For direct execution it is copied
to an ephemeral private host config. Credentials never appear in argv. Tool stderr
is captured and replaced with a generic failure message because tools can echo
credential-bearing URIs. Credential files are managed by the producer/user, not
automatically removed when a target retires.

### MongoDB consistency and tools

All dumps use `mongodump --archive` streamed to disk, optionally `--gzip` (default),
not PostgreSQL SQL files. `connection.database` selects one database. Without it,
the URI's database selection / native tool defaults apply; **omit a database path
from a remote URI to request a full-instance dump**.

`dump.oplog: true` requires a replica set, a full-instance dump, and suitable
privileges. It cannot be combined with `connection.database`; do not put a
single-database filter in the URI either. For standalone servers, multi-document
writes across collections are not guaranteed consistent: quiesce writers or use
an appropriate replica-set/snapshot strategy. Sharded clusters require their own
supported coordinated backup strategy. Test restoring users/roles and any
excluded system/local data; mongodump is not a raw filesystem backup.

Remote/direct execution needs compatible MongoDB Database Tools on the host
(with `--config` support, version 100.3.0+). Container mode uses the image's tools
and does not install host tools. Existing host `mongodump` is checked before
changing timers. Optional `mongodump_install_tools: true` installs
`mongodump_tools_package` (default `mongodb-database-tools`) from already configured
APT repositories. There is no unverified download/latest-version scraping or
architecture fallback. A custom `execution.mongodump_bin` can select a tool path.

## Lifecycle, reliability and check mode

- Owner/id rules and manifest schema are the same as PostgreSQL:
  `{"schema_version": 1, "owner": "my-project", "targets": [...]}`.
- Ids and outputs must be unique across producers; paths cannot traverse outside
  the output root. The registry is trusted user-owned configuration.
- The helper replaces only `<owner>.json`. `targets: []` retires that producer's
  schedules; `mongodump_declare_state: absent` removes its manifest on teardown.
  **Archives and credential files are never deleted automatically.**
- `mongodump_declare_reconcile: false` batches publication; include
  `install_backup_node_mongodb` once afterward. Default is immediate reconciliation.
- Stopped/absent Compose DBs return success with `Backup skipped`, preserving the
  last archive. Daemon/config errors and errors from a running DB still fail.
  A successful recheck handles a container stopping during a failed dump.
  `--require-available` disables skipping for a manual fresh-backup requirement.
- Same-directory staging, fsync and atomic replacement preserve previous archives
  on failed/empty dumps. A shared file lock serializes timer/manual runs. Existing
  Restic `*.tmp`/`*.lock` exclusions cover staging/lock files.
- Deploying the role does not explicitly run a dump. A persistent timer can catch
  up shortly after activation. Inspect the journal and monitor archive freshness;
  a skipped run is not a new dump.
- `--check` overlays the proposed owner on other persisted declarations, validates
  the contract/duplicate outputs, and previews units without installing tools,
  writing credentials, contacting MongoDB/Docker/systemd, or requiring a runner.
  Filesystem/credential/tool checks happen in apply mode. The account and Python
  must exist; batched unpublished declarations aren't accumulated in check mode.

## Existing endpoint migration

`playbooks/backup/node/mongodb.yaml` is now a thin launcher. If the old
`mongotools_mongodb_endpoints` is explicitly defined, it publishes a dedicated
`legacy-mongotools` producer. Each `{uri, out_file}` becomes a stable id derived
from `out_file`, a private native config, and an archive at:

```
/etc/mongodb/db_backup/legacy/<out_file>
```

Old root-level archives are retained, not overwritten/moved/deleted. Output
basenames must be safe and unique. Empty `[]` is valid and retires the old
producer's targets. Only this explicitly enrolled compatibility producer removes
the former root cron entry (`Mongotools backup`, configurable via the old
`mongotools_mongodb_backup_cron_job_name`); other producers do not stop that cron.
Old group/permissions/cron-prefix settings and the old install/dump shell
scripts are no longer used. No URI goes into the new manifests.

The repository's `install_analytics_server_mongodb` role installs **only an
exporter**, not a MongoDB database. Its monitoring endpoints are deliberately not
automatically enrolled. Add a producer declaration to the actual deployment role
or publish a remote target explicitly as shown above.

## Remote storage and rollout

New-host setup templates include a MongoDB Autorestic location using
`mongodump_backup_location_root_path`. **Existing hosts must add that directory
to their own Autorestic locations**, then redeploy Restic configuration; databases
under `/etc` are not covered by a home-only backup. MongoDB reconciliation is
included in the backup scenario and node profiles before Restic.

```bash
ansible-playbook -i inventory/production.ini playbooks/backup/node/mongodb.yaml \
  --limit HOST --check
ansible-playbook -i inventory/production.ini playbooks/backup/node/mongodb.yaml \
  --limit HOST
# New service roles publish with --tags declare_backups, as for PostgreSQL.
```

Run as the backup/Docker user:

```bash
systemctl --user list-timers 'ansible-mongodb-backup-*'
systemctl --user start ansible-mongodb-backup-my-project-db.service
journalctl --user -u ansible-mongodb-backup-my-project-db.service
python3 ~/.local/lib/ansible-backup/mongodb_backup.py \
  --manifest-dir ~/.config/ansible-backup/mongodb.d \
  --output-root /etc/mongodb/db_backup --target my-project-db --require-available
# Example restore, on a separate tested restore target:
mongorestore --config /path/to/private-restore.yaml --gzip --archive=/path/to/dump.archive.gz
```

For oplog archives, use the supported `mongorestore --oplogReplay` workflow and
verify it on a test instance. Never restore over production without a plan.

## Tests

```bash
python3 -m unittest discover -s roles/install_backup_node_mongodb/tests -p 'test_*.py' -v
ansible-playbook -i localhost, roles/install_backup_node_mongodb/tests/contract.yml
```

Tests use fake MongoDB tools and local fixture inventories. They verify private
config handling, atomic failures, locking, skips, direct/Compose declarations,
check-mode overlays, and systemd syntax; they do not prove live MongoDB restores.
