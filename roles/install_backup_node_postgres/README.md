# PostgreSQL backups

Service roles publish **persistent, user-owned JSON manifests**. This role knows
nothing about service names or bot instance counts: it reads the registry,
validates targets, installs a generic dump runner, and reconciles user systemd
services/timers. Restic/rclone/Autorestic remain responsible for remote storage.

## Rootless Docker and paths

Defaults (shared in `inventory/group_vars/all/0_defaults/backup_postgres.yaml`):

- User: `standard_user` (`pgdump_backup_user`).
- Registry: `/home/<user>/.config/ansible-backup/postgres.d/*.json` (`0700` directory,
  `0600` manifests).
- Runner: `/home/<user>/.local/lib/ansible-backup/postgres_backup.py`.
- Units: `/home/<user>/.config/systemd/user/ansible-postgres-backup-<id>.{service,timer}`.
- Docker endpoint: the backup user's configured Docker CLI context/environment;
  no socket path is guessed or forced.
- Dumps: `/etc/postgres/db_backup/<subdirectory>/<filename>` (existing paths retained).

The role enables lingering and starts the user's service manager using privileged
setup tasks. No Docker systemd dependency is added by default: a rootless daemon
may run without a user unit named `docker.service`, and user units cannot depend
on the system manager's Docker unit. The runner connects directly to the Docker
socket selected by the user's Docker CLI configuration. It does **not** install
Docker: deploy Docker first. Running the client as an unprivileged user does not
by itself prove the daemon is rootless; `docker info` reports that separately.

### Docker endpoint selection

By default, the runner preserves `DOCKER_HOST`, `DOCKER_CONTEXT` and
`DOCKER_CONFIG` when inherited, otherwise Docker uses the user's persisted current
context. Generated units set `HOME` to the backup user's home but do not force
`DOCKER_HOST` or `DOCKER_CONTEXT`. Systemd does not inherit your interactive shell,
so if shell-only environment selects Docker, configure that endpoint explicitly:

```yaml
pgdump_backup_docker_context: my-context
# OR, not both:
# pgdump_backup_docker_host: unix:///actual/path/docker.sock
```

These shared inventory settings apply to scheduled and panel manual/pre-upgrade
callers. A target can pin `execution.docker_context` or `execution.docker_host`;
its selection takes precedence over global/inherited configuration. The runner
never retries another Docker daemon as a fallback.

Diagnose selection on the host with `docker context show`,
`docker context inspect --format '{{.Endpoints.docker.Host}}'`, and
`printenv DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG`. The usual rootless socket
`/run/user/<uid>/docker.sock` must not be assumed merely because `docker ps` works.
Redeploy the backup role after changing endpoint settings or updating the runner.


If Docker is managed by a known user unit, optionally set
`pgdump_backup_docker_unit: custom-rootless-docker.service` in inventory, or
`execution.docker_unit` in a target. This adds `After` and `Requires` for that
**user-manager** unit; it must exist. A target can set `docker_unit: ''` to opt out
of a configured global dependency. Changing this option requires reconciliation
with `playbooks/backup/node/postgres.yaml` to replace the unit files.
Dump execution always runs as the backup user. Legacy output directories are made
user-owned, with `0700` permissions; new dump files are `0600`. Restic currently
runs as root and can still read them. If your Restic process uses a different
unprivileged account, arrange access explicitly.

For an entirely home-based output root, override `pgdump_backup_location_root_path`
in inventory. The generated Autorestic PostgreSQL location already references
this variable; redeploy Autorestic after changing it. Set `pgdump_migrate_legacy:
false` once legacy cron jobs/permissions no longer require migration. Lingering
setup still requires privilege. Changing users is an explicit migration: registries
and timers belong to a particular account.

## Producer contract (schema version 1)

A producer calls `kwtoolset/declare_postgres_backup` with a stable owner and its
**complete current target list**, including an empty list for zero instances.
Files are atomically replaced, and other producers are left untouched.

```yaml
- name: Declare this application's backup requirements
  ansible.builtin.include_role:
    name: kwtoolset/declare_postgres_backup
  vars:
    pgdump_declare_owner: my-application
    pgdump_declare_targets:
      - id: my-application-db
        project_path: /home/example/apps/my-application
        execution:
          driver: compose_exec
          skip_if_unavailable: true  # default; false makes a stopped DB fail the job
          service: db
          project_name: my-application  # must match deployment's Compose project
        connection:
          source: container_environment
        dump:
          scope: cluster
          format: plain
        output:
          subdirectory: my-application
          filename: dump.sql
        schedule:                  # optional; otherwise role defaults
          calendar: '*-*-* 00:00:00 UTC'
          randomized_delay: 15min
```

Published form: `{"schema_version": 1, "owner": "my-application", "targets": [...]}`.
Owner and target ids use ASCII alphanumerics, `_` and `-`, starting with an
alphanumeric. Ids must be unique across the registry and at most 120 characters.
Output paths must be unique, relative to the output root, and cannot traverse
parents or symlinks outside that root. Manifests are trusted configuration owned
by the Docker user, not an untrusted-command execution interface.

### Execution, credentials and dump scope

- `compose_exec`: executes `docker compose ... exec -T <service>` using the target's
  absolute project path and `docker-compose.yml`. Optional `project_name` must
  match how the project was deployed. Optional `docker_host`/`docker_bin` override
  the CLI endpoint/binary. `docker_context` pins a named Docker context instead
  of a host; do not specify both context and host.
- `connection.source: container_environment` (default for Compose) reads
  `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` **inside the database
  container**. Optional `connection.user` and `connection.database` override the
  user/initial database. No database passwords are duplicated into manifests or
  unit files. Local socket PostgreSQL authentication must permit this connection.
- `direct`: executes host-installed PostgreSQL clients. Set
  `connection.url_file` to an absolute, private (`0600` or stricter) file containing
  a libpq PostgreSQL URI. It supplies credentials via environment, not argv.
  Supported URI parameters: `sslmode`, `sslrootcert`, `sslcert`, `sslkey`,
  `connect_timeout`. Application-only parameters such as `schema` are rejected.
  Host client version must be compatible with the server.
- `dump.scope: cluster` (default): `pg_dumpall --clean`, plain SQL only; preserves
  the old cluster-wide dump behavior, including roles. Requires an appropriately
  privileged PostgreSQL user.
- `dump.scope: database`: `pg_dump`, `format: plain` or `custom`. A single database
  dump does not include cluster roles; account for that when restoring.

Service-specific target variables can override the defaults for panel,
Jolymmiels, Bedolaga, infra-billing, and Matrix Synapse; bots expand their own
settings lists. Jolymmiels retains the current deployment's Compose project name
rather than assuming a different project for every instance.

### Stopped or absent database containers

For Compose targets, `execution.skip_if_unavailable` defaults to **true**, including
previously published manifests that omit the field. Before dumping, the runner
queries the selected project's running database service. A successful empty
result means the container is absent/stopped: it logs `Backup skipped`, returns
exit code 0, and leaves existing dumps untouched. If a container stops during a
failed dump, a fresh successful availability query can also turn that run into a
skip. Docker connectivity, invalid Compose configuration, and dump errors while
the container remains running still fail. A running-but-unhealthy PostgreSQL
server is not treated as a stopped container. Direct PostgreSQL targets retain
their normal failure behavior.

Set `execution.skip_if_unavailable: false` in a custom target, or use a project's
inventory variable to make all its default targets strict:

```yaml
vpn_server_remnawave_postgres_backup_skip_if_unavailable: false
# Other projects have equivalent switches:
# vpn_server_remnawave_tgbot_jolymmiels_postgres_backup_skip_if_unavailable
# vpn_server_remnawave_tgbot_bedolaga_postgres_backup_skip_if_unavailable
# infra_billing_postgres_backup_skip_if_unavailable
# matrix_synapse_postgres_backup_skip_if_unavailable
```

Bot instance settings can override the project switch with
`postgres_backup_skip_if_unavailable: false`. Redeploy the producer with
`--tags declare_backups` after changing a project/instance setting. Skipping is
not a new successful dump; monitor dump age separately if a stopped database must
not go unnoticed. The CLI option `--require-available` overrides skipping for a
single invocation. Panel pre-upgrade and controller-download callers use this
option so they cannot silently use a stale dump.

### Lifecycle

By default the helper immediately reconciles all persisted manifests. To publish
several producers and reconcile once afterward, set `pgdump_declare_reconcile:
false`, then include `install_backup_node_postgres`.

On uninstall call the same helper with `pgdump_declare_state: absent` and the owner.
The Remnawave removal playbook already does this for the panel and both bot roles.
Removing instances (even all instances) replaces that owner's list. Reconciliation
stops/disables/removes retired units; **it never deletes dump files**. Other
service uninstall workflows must remove their own manifest as part of teardown.

## Scheduling, monitoring and reliability

- Defaults: daily at midnight UTC, randomized up to 15 minutes, persistent timer.
  Override `pgdump_backup_calendar`, `pgdump_backup_randomized_delay`, and
  `pgdump_backup_timeout` (`1h`). A persistent timer may catch up shortly after
  being enabled; deployment does not explicitly start the oneshot service.
- Services use `manage_state: false` with `0x0I.systemd`. Requires the installed
  role version supporting user scope and `manage_state` (as used in this repo).
- `pgdump_backup_monitor_argv` is an optional executable/argv prefix, not shell
  syntax. `analytics_node` supplies the existing monitor wrapper with a per-target
  job name. The wrapper must propagate the command's exit status.
- Failed/empty dumps return nonzero and leave the previous dump untouched.
- Dumps use a same-directory temporary file, fsync and atomic replacement.
- An output-file lock serializes timer/manual/pre-upgrade runs. Never delete lock
  files while jobs may be running. Autorestic's existing `*.tmp`/`*.lock` excludes
  prevent snapshots of staging/lock files.
- Legacy root cron entries are removed only when their Ansible-managed job points
  into `pgdump_legacy_script_directory` (defaults to the former backup project)
  and its producer has declared the matching `legacy_script_subdirectories`.
  This lets you migrate producers individually without stopping another
  producer's still-legacy cron backups. Old scripts/dumps are retained but no
  longer deployed by this role.
- Check mode validates the full proposed target contract and duplicate ids/outputs
  using an in-memory overlay of the producer being replaced/removed and the other
  persisted manifests. It prints target/unit additions and retirements without
  creating directories, installing the runner, starting user services or dumping
  databases. The backup account and Python must already exist. Filesystem
  symlink/permission checks and legacy cron migration are deferred to apply mode.
  Batched declarations with `pgdump_declare_reconcile: false` are not persisted in
  check mode; use the default immediate reconciliation to preview each producer.

## Rollout and manual use

Publish declarations without redeploying application containers:

```bash
# Preview first, including on a host without the registry or runner:
ansible-playbook -i inventory/production.ini \
  playbooks/anti_censorship/server/remna.yaml --tags declare_backups --limit HOST --check
ansible-playbook -i inventory/production.ini \
  playbooks/anti_censorship/server/remna.yaml --tags declare_backups --limit HOST
# Repeat for each already-deployed bot/infra-billing/Matrix playbook as applicable.
ansible-playbook -i inventory/production.ini \
  playbooks/backup/node/postgres.yaml --limit HOST
```

Declare **all existing producers before considering rollout complete**. The
standalone backup playbook cannot infer services whose roles have not published
manifests. Service roles publish only on hosts in `backup_restic_node`.

Run as the Docker user:

```bash
systemctl --user list-timers 'ansible-postgres-backup-*'
systemctl --user start ansible-postgres-backup-remnawave-panel-db.service
journalctl --user -u ansible-postgres-backup-remnawave-panel-db.service
python3 ~/.local/lib/ansible-backup/postgres_backup.py \
  --manifest-dir ~/.config/ansible-backup/postgres.d \
  --output-root /etc/postgres/db_backup --target remnawave-panel-db
```

Panel pre-upgrade and controller-fetch callers use this same runner, always
requesting a fresh dump instead of skipping because an older dump exists, and
requiring a running database even when scheduled backups permit skips. The
optional controller-fetch role is dynamically included only with
`--tags backup_controller`; its prerequisites do not run under `declare_backups`.
With `--check`, controller fetch only reports its intended operation.

## Local tests

```bash
python3 -m unittest discover -s roles/install_backup_node_postgres/tests -p 'test_*.py' -v
ansible-playbook -i localhost, roles/install_backup_node_postgres/tests/contract.yml
```

Test restoration separately before relying on any backup. Tests here use fake
PostgreSQL/Docker commands; they do not prove live database or user-manager access.
