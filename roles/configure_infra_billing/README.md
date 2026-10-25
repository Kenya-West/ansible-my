# configure_infra_billing

Reads or additively reconciles infra-billing records from the independent
`infra_providers` catalog in `host_vars/<billing-server>/infrastructure/providers.yaml`
and related hosts' `infrastructure` data. Uses the
controller-only `action_plugins/infra_billing.py` action. No SSH,
provider API calls, Remnawave writes or deletion. A missing connector service
can trigger an infra-billing account import; this may refresh balances and
payment history but never charges or tops up a provider account.
Country is collected from each node's existing `country_code_upper` variable,
not duplicated in infrastructure data.

Standalone domain records are supplied as `infrastructure_domains` and separate
`infra_billing_domain_bindings` on the billing server, typically in
`host_vars/<server>/infrastructure/domains.yaml`. They have registrar/account
ownership, not VPS host relations. `type: domain` and domain-name externalId are
projected at the API boundary. Missing manual domains require verified billing;
connector-managed domains retain their API price/due date.

```sh
# Domains only: avoids unrelated enabled hosts and provider bindings.
ansible-playbook -i inventory/production.ini \
  playbooks/observability/server/infra_billing_domains.yaml --limit=<server> --check
```

Full `infra_billing_sync.yaml` includes enabled domains too. Domain-only sync
limits provider writes to enabled domain accounts. The console show playbook also
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
  kind independently of API state. Missing bindings for referenced accounts are
  derived from this declaration; explicit `infra_billing_provider_bindings` still
  provide names, kind overrides and adoption UUIDs. Conflicting kinds fail.
- For a missing connector-managed service, `infra_billing_sync_missing_services`
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

## Configuration errors

A driver error identifies the host and provider/account: API connections need an
explicit `connection.driver` (such as `billmgr`) unless the API binding supplies
`kind`. An enabled but absent connector account also needs creation credentials
in the private catalog; a missing stored account cannot reuse secrets from a
deleted binding. Enabled manual services need verified `infrastructure.billing`
(amount, currency and supported interval). Historical To Do reminder dates are
not sufficient. Reconciliation fails before writes rather than guessing costs,
silently changing API accounts to manual, or skipping enabled exports.

Run from the repository root using the existing `action_plugins/` discovery;
no additional `ansible.cfg` settings are needed. The sibling
`action_plugins/infra_billing_utils/` package contains validation/projection.
Ansible core and controller Python standard library suffice. Uses the existing
`kwtoolset/resolve_host_relations` role to select this server's nodes.
To regenerate the local catalog from configured host sources, use the separate
`setup/infra_providers` role and repository-maintenance playbook.
