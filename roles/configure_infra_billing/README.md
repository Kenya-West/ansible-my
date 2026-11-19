# configure_infra_billing

Reads or additively reconciles infra-billing records from the independent
`infra_providers` catalog in `host_vars/<billing-server>/infrastructure/providers.yaml`
and related hosts' `infrastructure` data. Uses the
controller-only `action_plugins/infra_billing.py` action. No SSH, direct
provider API calls, Remnawave writes or deletion. The full sync playbook refreshes
all enabled connector accounts through infra-billing, including accounts and
services absent from inventory. Scoped workflows import only missing services.
Both may refresh balances and payment history but never charge or top up a
provider account.
Country is collected from each node's existing `country_code_upper` variable,
not duplicated in infrastructure data.

Standalone domain records are supplied as `infrastructure_domains` and separate
`infra_billing_domain_bindings` on the billing server, typically in
`host_vars/<server>/infrastructure/domains.yaml`. They have registrar/account
ownership, not VPS host relations. `type: domain` and domain-name externalId are
projected at the API boundary. Missing manual domains require verified billing;
connector-managed domains retain their API price/due date.

```sh
# Domains only: avoids unrelated enabled hosts and provider accounts.
ansible-playbook -i inventory/production.ini \
  playbooks/observability/server/infra_billing_domains.yaml --limit=<server> --check
```

Full `infra_billing_sync.yaml` includes enabled domains too. It also refreshes
**every enabled non-manual account already in infra-billing**, even without a
catalog entry or an enabled inventory export. All connector-discovered entities
(services, domains, balances and supported payment history) are refreshed; manual
records still use additive inventory reconciliation. Disabled connector accounts
are skipped, never silently enabled. Projects are read/validated, not created.
Domain-only sync limits provider writes to enabled domain accounts and does not
perform the full refresh. The console show playbook also
lists declared domains, including disabled ones. Examples are commented in
[server domain template](../setup/server/templates/host/infrastructure/domains.yaml.j2).

See [data model, examples, commands and safety limits](https://github.com/Kenya-West/ansible-my/wiki/Infrastructure-providers-and-billing).

- Default action: `read`; `reconcile` is selected by `infra_billing_sync.yaml`.
- Inputs/defaults: [defaults/main.yml](defaults/main.yml).
- Output: private `infra_billing_gathered` fact for reads and a credential-safe
  compact reconciliation report printed with native `debug: msg` (list of lines).
  Exactly one `CREATE`, `UPDATE` or `SYNC` line is emitted per counted API
  operation, with the entity name/account and changed field names only.
  Unchanged/disabled records and nested before/after data are omitted. Provider
  creation includes its first account on the same line. A zero-change run prints
  only the header, count summary and `No changes.`
- `infra_billing_service.enabled` is explicit opt-in on each host.
- Billing intervals are restricted to 1 hour/day/month/year/once or 3 months.
  Unsupported intervals fail even on disabled exports when billing is declared;
  no cost normalization is performed.
- `playbooks/observability/server/infra_billing_show.yaml` prints a native
  structured report of projects, services, provider/account UUIDs and inventory
  matches. It excludes credentials and is read-only.
- `connection.driver: billmgr` (or another supported driver) declares connector
  kind independently of API state; non-API connections are `manual`. API
  identities live in the same catalog, in optional `infra_billing` blocks (see
  [Provider identities](#provider-identities)). The former
  `infra_billing_provider_bindings` variable is refused when non-empty.
- Full sync reconciles every catalog provider account
  (`infra_billing_include_unused_accounts: true`); the domains-only playbook and
  host onboarding reconcile only the accounts their enabled records use.
- `infra_billing_sync_all_accounts` defaults to false in the role and is enabled
  by `infra_billing_sync.yaml`. Each enabled connector account receives exactly
  one `SYNC` per run, after provider/account creation or credential updates.
  The action re-reads services before applying inventory project/description
  changes. Missing connector services with `service_id` are imported/adopted,
  including when inventory billing is present, rather than creating duplicates.
  Manual services with verified billing and no connector identity can still be
  created on connector accounts. Unlisted manual records remain untouched.
  Full refresh intentionally is **not a no-op on reruns**: it records sync runs
  and may refresh balances/payment history or mark missing managed services
  inactive. There is no deletion, provider-side provisioning, charging or top-up.
  `--check` plans account refreshes but performs only GETs; **it does not test
  connector health, provider authentication or whether imports will succeed**.
  Newly discovered entities and their follow-up PATCHes cannot be predicted
  until apply. A successful preview is not a successful sync.
  Full apply attempts every account even when one connector or sync HTTP request
  fails. Failed accounts get a `SYNC ... [FAILED: ...]` line with a fixed safe
  error category, never the raw connector error. Successfully refreshed accounts
  still receive their inventory annotations; failed accounts do not adopt stale
  services or create fallback records. The role prints the partial report, then
  fails the play so errors are not silently ignored. Check the account's sync
  history/error in infra-billing for the underlying provider failure. Requests
  are not automatically retried because a timed-out sync may have completed.
  Scoped onboarding still fails immediately on an unsuccessful account import.
  Use `-e infra_billing_sync_all_accounts=false` for the previous scoped behavior.
  `infra_billing_sync_missing_services=false` separately prohibits missing-service
  imports in scoped workflows; it does not disable an explicit full refresh.
- For a missing connector-managed service in a scoped workflow,
  `infra_billing_sync_missing_services`
  (default true) creates/updates the provider/account then requests account sync
  through infra-billing, re-reads services and adopts by `service_id`. Credentials
  are required for a new account. A normal second run skips sync entirely.
- Existing connector-managed services can omit billing data entirely; UUID or
  service_id adoption keeps connector cost/renewal date authoritative. An
  unimportable service fails, never creates a price-less manual duplicate.
- Seed-only `infrastructure.sources` and domain `sources` were removed: they
  were never used by reconciliation or catalog regeneration. Keep operational
  data in billing, service_id/service_url and verified policy fields, not legacy
  To Do provenance. `infrastructure_provider_sources` still configures live
  regeneration readers and is unrelated to the retired field.
- Supports `--check` (GET only); secrets are protected with `no_log`.

## Pull mode (infra-billing → host_vars, half-duplex)

`playbooks/observability/server/infra_billing_pull.yaml` (`tasks/pull.yml`) reads
services with a GET and updates **existing** values in each related node's
`host_vars/<host>/0_all/3_infrastructure.yaml`
(override with `infra_billing_pull_host_file_template`). Nothing is written to
infra-billing.

```sh
ansible-playbook -i inventory/production.ini \
  playbooks/observability/server/infra_billing_pull.yaml --check --diff   # preview
ansible-playbook -i inventory/production.ini \
  playbooks/observability/server/infra_billing_pull.yaml                  # apply
```

- Pulled: `infrastructure.billing.{amount,currency,interval,next_due_at}`,
  `infra_billing_service.{project_uuid,uuid}`.
- Match order: `infra_billing_service.uuid` (no fallback if it is gone), then
  `infrastructure.service_id` = billing externalId, then service name = host name.
  Ambiguous or double-claimed matches are skipped.
- Only keys already present are edited, as in-place text edits that keep comments,
  quoting and layout. Equivalent values (`370` vs `370.00`, `…Z` vs `….000Z`) are
  left alone. The result is re-parsed before writing.
- Never creates or removes files or keys. Hosts with a missing, symlinked,
  vault-encrypted or unparseable file, or with no matching service, are skipped
  with a warning and a `SKIP` line. No backups are made.

## Tests

```sh
python3 -m unittest discover -s roles/configure_infra_billing/tests -v
```

Mock API tests cover full refresh scope, GET-only checks, duplicate-import
prevention, connector-owned fields, manual reconciliation, isolated account
failures and safe reports. Isolated Ansible CLI tests verify the partial report
is printed before failing and that validation failures remain private/fatal.

## Provider identities

`infra_providers` is the single source for both connections and infra-billing API
identities. Every catalog account maps to one infra-billing provider/account:

| Field | Where | Default |
|---|---|---|
| provider display name | `<provider>.infra_billing.name` | catalog `name` |
| provider adoption UUID | `<provider>.infra_billing.uuid` | match by name |
| account adoption UUID | `accounts.<a>.infra_billing.uuid` | match by label |
| account label | `accounts.<a>.infra_billing.label` (may be `null`) | account key |
| connector kind | `accounts.<a>.connection.driver` | `manual` unless `type: api` |

Accounts with the same provider identity form one infra-billing provider and must
share one driver. To split one vendor key into several API providers (e.g. one per
registrar login), give each account its own `accounts.<a>.infra_billing.provider:
{uuid, name}`; it replaces, never merges with, the provider-level block. One API
identity cannot span two catalog providers. Examples:
[server providers template](../setup/server/templates/host/infrastructure/providers.yaml.j2).

`setup/infra_providers` regeneration maps live API providers back to catalog keys
through these identities and records the live identity for accounts that declare
none. Declared identities always win over API data.

## Switching a retired connector to manual billing

If a provider retires its API, set the catalog account's `connection.type` to
`manual` and remove `connection.driver`. Point its `infra_billing` identity at the
intended manual provider/account UUIDs, or remove those UUIDs (and use a new
`infra_billing.name` if the old connector provider keeps its name) to create new records.
Reconciliation does not convert a live provider's kind in place or adopt deleted
UUIDs. Remove a deleted service's `infra_billing_service.uuid` (or replace it with
an existing manual service UUID); keep the intended `project_uuid`.

Enabled manual exports need verified `infrastructure.billing.amount`, `currency`
and a supported `interval`. Optionally declare a verified `next_due_at`. A former
connector `service_id` is only metadata, not a price or a live billing UUID. The
role cannot recover prices/dates from a deleted connector service and will not
invent zero-cost records. Once the UUIDs and billing are updated, preview with
`--check`; the manual provider/account/service are created without account sync.

## Configuration errors

A driver error identifies the host and provider/account: API connections need an
explicit `connection.driver` (such as `billmgr`). An enabled but absent connector
account also needs creation credentials in the private catalog; a missing stored
account cannot reuse secrets from a deleted account UUID. Enabled manual services need verified `infrastructure.billing`
(amount, currency and supported interval). Historical To Do reminder dates are
not sufficient. Reconciliation fails before writes rather than guessing costs,
silently changing API accounts to manual, or skipping enabled exports.

The action keeps `no_log` for raw inputs/results, even if the caller removes it:
those can contain API tokens, account credentials and private read data. Expected
validation/request failures also carry a separate sanitized `public_error`. The
server role prints that message through a dedicated `fail` task, naming the
host/provider/account and required fix. It does not print request bodies, raw
connector errors or unexpected Python exceptions. Missing service UUIDs and
kind/driver conflicts are therefore visible without exposing secrets.

Run from the repository root using the existing `action_plugins/` discovery;
no additional `ansible.cfg` settings are needed. The sibling
`action_plugins/infra_billing_utils/` package contains validation/projection.
Ansible core and controller Python standard library suffice. Uses the existing
`kwtoolset/resolve_host_relations` role to select this server's nodes.
To regenerate the local catalog from configured host sources, use the separate
`setup/infra_providers` role and repository-maintenance playbook.
