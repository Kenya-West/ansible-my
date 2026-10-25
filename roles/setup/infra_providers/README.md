# setup/infra_providers

Controller-only repository maintenance. Regenerates the selected server's private
`host_vars/<server>/infrastructure/providers.yaml` from configured inventory
sources, preserving
existing fields, credentials and unrelated YAML keys. No host SSH, remote writes,
API credential reveal, billing synchronization or node-file changes.

```sh
ansible-playbook -i inventory/production.ini \
  playbooks/ansible/infrastructure/regenerate_providers.yaml --check
ansible-playbook -i inventory/production.ini \
  playbooks/ansible/infrastructure/regenerate_providers.yaml
```

Defaults: [defaults/main.yml](defaults/main.yml). Catalog owner is
`setup_infra_providers_server` (default first analytics server); pass it explicitly
when multiple servers exist. Only that server receives the catalog, not global
`group_vars`. Controller onboarding reads `hostvars[resolved_server].infra_providers`.
Providers describe identity/connections only; `sources.todo` is rejected.
Legacy host/domain `sources` seed metadata is no longer stored. The explicit
`infrastructure_provider_sources` configuration below is different: it controls
live readers during catalog regeneration and remains supported.

Sources on each host:
- `infrastructure_provider_definitions`: independent provider/account mapping;
- `infra_billing_api_url` + `infra_billing_api_token`: existing GET access, or
  `infrastructure_provider_sources.infra_billing` overrides;
- `infrastructure_provider_sources.remnawave.enabled: true`: optional panel
  GETs through the collection role, with all desired-state stages disabled.

No source is inferred from the hostname, inherited `infra_providers`, or
`domains_keys`. `infrastructure: {provider: ..., account: ...}` alone is a
reference, not enough information to rebuild a provider definition.

Reports used/skipped hostnames and source status. API failures and conflicting
explicit declarations abort before file writes. Existing values win over API
metadata; explicit host definitions override specified fields. No pruning.
`setup_infra_providers_hosts` selects source hosts (default all except localhost);
`--limit` selects the execution host, not the sources.

GETs run in check mode; no file/directory/backup is created in check mode.
Writes are atomic, mode `0600`, with an Ansible timestamped backup when an
existing file changes. Existing template strings are preserved without
resolution. Fully vault-encrypted destination files are refused rather than
silently replaced by plaintext; use a separate generated file and vault it
manually. Credential-bearing inputs/results are `no_log` and diffs disabled.

Sources and examples are documented beside the generated variables:
[server infrastructure template](../server/templates/host/0_all/3_infrastructure.yaml.j2).
The examples are commented out; uncomment only the sources this server should
supply. YAML comments in the generated file do not enable API reads.

Minimal explicit source in an authoritative host's host_vars:

```yaml
infrastructure_provider_definitions:
  vendor:
    name: Example Hosting
    website: https://vendor.example
    login_url: https://clients.vendor.example
    accounts:
      main:
        connection:
          type: manual

infrastructure_provider_sources:
  remnawave:
    enabled: true
    url: https://panel.example
    token: "{{ vault_remnawave_token }}"
    provider_keys:
      Example Hosting: vendor
```

Use existing `infra_billing_api_url/token` for billing GETs, or provide
`infrastructure_provider_sources.infra_billing` overrides (`url`, `token`,
`provider_keys`, `account_keys`). Set `enabled: false` to exclude that source.

See [the wiki guide](https://github.com/Kenya-West/ansible-my/wiki/Infrastructure-providers-and-billing)
for the full provider/account model and merge policy.
