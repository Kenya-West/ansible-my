# setup/infra_billing_host

Controller-only add/adopt workflow for **one** inventory host on its existing
`analytics_server/infra_billing` host relation. No SSH, Remnawave writes, project
creation or guessed connector kinds. Missing services can be imported through
infra-billing's account sync, which may also import balances/payment history.

```sh
ansible-playbook -i inventory/production.ini \
  playbooks/ansible/infrastructure/add_host_to_billing.yaml \
  -e setup_infra_billing_host=vendor-de-1 --check
```

Choose a project by name or UUID from the native structured console report.
Optional service UUID adopts a differently named existing service. Without it,
existing account/name or provider service_id matching is used. Missing connector
services are imported using declared `connection.driver` and provider/account
credentials; verified manual billing instead creates a manual service. An apply
always previews first and asks for `yes`.

Unattended preview/apply:

```sh
ansible-playbook -i inventory/production.ini \
  playbooks/ansible/infrastructure/add_host_to_billing.yaml \
  -e setup_infra_billing_host=vendor-de-1 \
  -e 'setup_infra_billing_project=My Project' \
  -e setup_infra_billing_confirm=true --check
# Remove --check only after reviewing. confirm=true authorizes the apply.
```

Requirements:
- Host `infrastructure` has provider/account plus either verified amount/currency
  and a supported interval (1 hour/day/month/year/once or 3 months), or a provider
  `service_id` to import/adopt through a declared API driver.
- Related billing server owns its catalog at
  `host_vars/<server>/infrastructure/providers.yaml`. Declare
  `accounts.<key>.connection: {type: api, driver: billmgr, api_url: ...}` plus
  credentials in Vault for first creation. Existing secrets remain in billing.
  Explicit `infra_billing_provider_bindings` are optional when no override is
  needed; otherwise declare the intended provider/account UUIDs or names.
  Do not copy environment-specific UUIDs to a fresh billing database.
- Default local file `host_vars/<host>/0_all/3_infrastructure.yaml` exists and
  contains `infrastructure`. Override `setup_infra_billing_host_file` if needed.
  Fully vaulted files/symlinks and duplicate service definitions are refused.

Only the selected provider account and service are explicitly reconciled. A
missing connector service triggers **account-wide** import through infra-billing;
other services/balances/payment history on that account may be refreshed or
marked inactive by the connector. It never charges or transfers funds. Set
`infra_billing_sync_missing_services: false` on the server to prohibit imports.
Once the service exists, reruns skip the import and are idempotent. Provider
identity metadata may also be reconciled. Existing
connector-managed cost/date/name/type remain untouched; project assignment is
authoritative. Explicit missing/ambiguous UUIDs fail without creating a duplicate.

After apply, the host file retains unrelated YAML keys and literal templates,
with `infra_billing_service.enabled: true`, project UUID and resolved service UUID.
Atomic copy, backup and mode `0600` protect the local file. Check mode sends GETs
only, predicts API/file changes and creates no backups; a not-yet-created service
UUID is shown as null. Formatting/comments may change on save.

API and filesystem writes are not one transaction: if local saving fails after
remote apply, rerun with the same names or explicit UUID. No rollback/deletion.
Saved service UUIDs survive project moves. A later full sync will enforce the
project saved in the host file, including after a manual UI move.

## First provisioning without API UUIDs

```yaml
# host_vars/<billing-server>/infrastructure/providers.yaml
infra_providers:
  waicore:
    name: Waicore
    login_url: https://my.waicore.com/billmgr
    accounts:
      main:
        connection:
          type: api
          driver: billmgr
          api_url: https://my.waicore.com/billmgr
          credentials:
            username: "{{ vault_waicore_username }}"
            password: "{{ vault_waicore_password }}"
            # totp_secret: "{{ vault_waicore_totp_seed }}"
```

```yaml
# host_vars/waicore-de-8/0_all/3_infrastructure.yaml
infrastructure:
  provider: waicore
  account: main
  service_id: '91046'  # BILLmanager resource ID, not infra-billing UUID
infra_billing_service:
  enabled: false     # onboarding previews/enables it after confirmation
```

Run `add_host_to_billing.yaml -e setup_infra_billing_host=waicore-de-8` and choose
an existing project by name. No `infra_billing_provider_bindings` is required for
this simple declaration. HSHP/DeepHost use their own driver/endpoints/credentials
and provider service IDs in exactly the same way.

An existing account with a secret-presence flag explicitly false may receive
that missing secret from YAML; present/unknown secrets remain untouched unless
rotation is enabled. Existing `kind: manual` cannot be changed to billmgr through
the immutable provider API: select a separate identity explicitly instead.

## First provisioning safety

Sync is used only when a price-less enabled service is missing and its driver
is non-manual. It requires `service_id`, and runs at most once per account in a
single reconciliation. API import returns a sync status; errors fail the run.
The service must actually appear after import; no made-up manual record is
created. Future service UUIDs remain null in check mode.

Account sync itself writes run/balance/payment history. It is deliberately not
performed on every run: idempotent reruns with matching services use GETs and
only changed fields receive PATCHes. Imported prices/dates are connector-owned.
Other services on that account can be refreshed/marked inactive by infra-billing.
There is no server-wide sync or provider-side provisioning/charging.

## Defaults and configuration

Defaults: [defaults/main.yml](defaults/main.yml). `--limit` selects localhost,
not the node: use `setup_infra_billing_host`. Console identifiers/costs are
intentionally visible/logged; API credentials are `no_log`.
