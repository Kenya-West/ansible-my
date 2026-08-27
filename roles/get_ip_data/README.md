get_ip_data
===========

Finds out where a host looks like it is, from the host itself.

It asks up to nine providers — four `community.general` modules and five plain HTTPS/HTTP
endpoints — maps every answer onto a single schema, and merges them into one result. It is
built for hosts behind aggressive filtering, where most providers are expected to be
unreachable: every provider is queried inside its own `block`/`rescue`, so a timeout, a TLS
reset, a captive portal or a rate limit takes down that provider and nothing else.

Requirements
------------

- `community.general` (already in `roles/requirements.yaml`) — for the four info/facts modules
  and for the `counter` filter used when tallying votes.
- Outbound HTTPS from the **managed host**, not from the controller. Everything runs on the
  target, which is the whole point: the answer describes the target's route to the internet.

No API keys, no accounts, no signup. Every provider in the catalog answers keyless requests.

Providers
---------

Community modules are listed first, so they win the twin preference and the vote tie-breaks.

| id                 | type   | service         | endpoint                          | key needed | notes |
|--------------------|--------|-----------------|-----------------------------------|-----------|-------|
| `ipbase_info`      | module | ipbase.com      | `https://api.ipbase.com/v2/info`  | no        | richest free answer; a key only raises the quota and unlocks the `security` block |
| `ipinfoio_facts`   | module | ipinfo.io       | `https://ipinfo.io/json`          | no        | sets host facts as a side effect, see the caveats |
| `ip2location_info` | module | ip2location.io  | `https://api.ip2location.io/`     | no        | module talks to the keyless endpoint; low daily quota |
| `ipapi_is`         | http   | ipapi.is        | `https://api.ipapi.is/`           | no        | ~1000/day; keyless replies are the short form |
| `ip_api_com`       | http   | ip-api.com      | `http://ip-api.com/json/`         | no        | 45/min; **plain HTTP only**, TLS is a paid feature |
| `ipapi_co`         | http   | ipapi.co        | `https://ipapi.co/json/`          | no        | 1000/day; refuses datacenter ranges with HTTP 429 |
| `db_ip_com`        | http   | db-ip.com       | `https://api.db-ip.com/v2/free/self` | no     | 1000/day; country/region/city only, no coordinates |
| `ipinfo_io`        | http   | ipinfo.io       | `https://ipinfo.io/json`          | no        | twin of `ipinfoio_facts`, only queried when the module failed |
| `ipify_facts`      | module | ipify.org       | `https://api.ipify.org/`          | no        | IP address only, no geolocation; queried last |

### Endpoints that were checked and left out

| service | why |
|---------|-----|
| `ipregistry.co` / `api.ipregistry.co` | keyless requests are answered with `401 MISSING_API_KEY`. The `tryout` key from their docs works, but it is still a key and it is shared and throttled, so the service does not belong in a keyless catalog. |
| `ipinfo.io/lite` | the newer lite API rejects tokenless calls with `403 Unknown token`. The classic `https://ipinfo.io/json` used above is unaffected. |

`community.general.ip2location_info` was checked too: despite the vendor name it uses the
keyless `api.ip2location.io` endpoint and takes no `api_key` option at all.

Policies
--------

`get_ip_data_policy: check_all`
: Query every enabled provider, then merge. Slower and chattier, but it survives most of the
  catalog being blocked and it shows you which providers disagree.

`get_ip_data_policy: first_successful` (default)
: Stop at the first provider that returns every field in `get_ip_data_required_fields`. On a
  healthy host that is one request. Providers that answered but fell short of the required
  fields still count towards the result, so a partial answer is never thrown away.

How the answers are merged
--------------------------

Plain majority vote, one vote per provider, per field. Three providers saying `RU` and two
saying `FR` gives `RU`. A tie goes to the provider that answered first, which is why the
catalog puts the community modules at the top.

Coordinates are not voted on — no two providers report the same point. They are the median of
the sources that agree on the winning country, which keeps the result on a real location
instead of the midpoint of two cities.

The vote is only as good as the agreement between providers. `country_code` and `asn` are
reliable. `city`, `region_name`, `isp` and `org` are spelled differently by everyone
(`True Online` vs `TRUE BROADBAND` vs `TRUE INTERNET CORPORATION CO. LTD.`), so they routinely
end in a 1-1-1 tie decided by provider order. The full tally is published under `consensus`
and printed on the `contested` line of the report, so you can always see how thin a win was.

Result schema
-------------

Every provider answer, and the merged result, uses these keys. A key a provider cannot fill is
dropped rather than set to `null`, so `is defined` is a meaningful test.

| key | notes |
|-----|-------|
| `ip`, `ip_version` | `ip_version` is derived from the address when the provider does not say |
| `hostname` | reverse DNS, only ipinfo.io and ip-api.com report it |
| `continent_code`, `continent_name` | code upper-cased |
| `country_code`, `country_name` | code upper-cased; `country_name` spelling varies by provider |
| `region_code`, `region_name` | providers disagree about what a region code is (`TH-52` vs `20`) |
| `city`, `zip` | |
| `latitude`, `longitude` | floats, rounded to 4 decimals |
| `timezone` | IANA name |
| `utc_offset` | **seconds** east of UTC; only filled by providers that report it that way |
| `asn` | plain integer, `AS` prefix stripped |
| `asn_org`, `isp`, `org` | |
| `is_mobile`, `is_proxy`, `is_vpn`, `is_tor`, `is_hosting`, `is_abuser` | advisory, providers disagree a lot |

Role variables
--------------

See [defaults/main.yml](defaults/main.yml) for the full annotated list.

| variable | default | meaning |
|----------|---------|---------|
| `get_ip_data_policy` | `first_successful` | `check_all` or `first_successful` |
| `get_ip_data_required_fields` | `[ip, country_code]` | what makes an answer complete, and what stops `first_successful` |
| `get_ip_data_providers` | `[]` | provider ids to query, empty means all of them |
| `get_ip_data_disabled_providers` | `[]` | provider ids to never query |
| `get_ip_data_prefer_modules` | `true` | query an HTTP endpoint only when the module for the same service failed |
| `get_ip_data_timeout` | `8` | seconds per request |
| `get_ip_data_retries` | `2` | attempts per provider |
| `get_ip_data_retry_delay` | `2` | seconds between attempts |
| `get_ip_data_validate_certs` | `true` | |
| `get_ip_data_user_agent` | `ansible-get-ip-data/1.0` | |
| `get_ip_data_language` | `en` | ipbase.com localisation |
| `get_ip_data_ipbase_apikey` | `""` | optional, only raises the ipbase quota |
| `get_ip_data_fact_name` | `ip_data` | name of the fact that receives the merged result |
| `get_ip_data_fact_cacheable` | `false` | write the merged result to the fact cache |
| `get_ip_data_show_report` | `true` | print the summary |
| `get_ip_data_show_sources` | `false` | also print every provider answer |
| `get_ip_data_fail_when_no_result` | `true` | fail the play when nothing answered |
| `get_ip_data_provider_catalog` | see defaults | the providers themselves, override to reorder or add one |

What the role produces
----------------------

A fact named by `get_ip_data_fact_name` (`ip_data` by default) holding the merged schema
fields plus:

| key | meaning |
|-----|---------|
| `policy` | the policy that produced this result |
| `resolved` | at least one provider answered |
| `complete` | the merged result carries every `get_ip_data_required_fields` entry |
| `queried`, `succeeded`, `failed` | provider ids |
| `skipped` | providers that were never contacted, with the reason |
| `consensus` | the full vote tally, `{field: {value: votes}}` |
| `sources` | every provider answer: `provider`, `type`, `service`, `endpoint`, `ok`, `error`, `data` |

Two more facts are left behind for convenience: `get_ip_data_results` (the same list as
`sources`) and `get_ip_data_skipped`.

Using the output facts
-----------------------

Guard a task on how trustworthy the answer is before acting on it — `resolved` says at least
one provider answered, `complete` says the merged result carries every field in
`get_ip_data_required_fields`:

```yaml
- name: Work out where this host looks like it is
  ansible.builtin.include_role:
    name: get_ip_data

- name: Refuse to deploy the exit node inside the censored country
  ansible.builtin.assert:
    that:
      - ip_data.resolved
      - ip_data.country_code != 'RU'
    fail_msg: "{{ inventory_hostname }} egresses through {{ ip_data.country_code | default('an unknown country') }} ({{ ip_data.asn_org | default('unknown ASN') }})"
```

Register the exit country in inventory, and warn instead of failing when nothing answered:

```yaml
- name: Record where this host egresses
  ansible.builtin.set_fact:
    exit_country: "{{ ip_data.country_code | default('UNKNOWN') }}"
    exit_asn: "{{ ip_data.asn | default('?') }}"

- name: Warn when the location could not be confirmed
  ansible.builtin.debug:
    msg: "⚠️  {{ inventory_hostname }}: no provider answered, cannot confirm the egress country"
  when: not ip_data.resolved
```

Branch on which provider actually answered — useful when only some fields matter and you would
rather skip a task than trust a thin vote:

```yaml
- name: Only trust the ASN when ipbase.com or ip-api.com confirmed it
  ansible.builtin.debug:
    msg: "AS{{ ip_data.asn }} ({{ ip_data.asn_org }})"
  when: ip_data.succeeded | intersect(['ipbase_info', 'ip_api_com']) | length > 0
```

Fan the merged result out to every host in the play, to spot outliers across a fleet that is
supposed to share one egress IP:

```yaml
- hosts: vpn_servers
  tasks:
    - ansible.builtin.include_role:
        name: get_ip_data

    - name: Collect one fact per host, on the play's first host
      ansible.builtin.set_fact:
        fleet_exit_countries: >-
          {{ fleet_exit_countries | default({}) | combine({inventory_hostname: ip_data.country_code | default('UNKNOWN')}) }}
      delegate_to: "{{ groups['vpn_servers'] | first }}"
      delegate_facts: true

    - name: Report hosts that disagree with the fleet's majority country
      ansible.builtin.debug:
        msg: "{{ inventory_hostname }} looks like it is in {{ ip_data.country_code }}, most of the fleet is not"
      when:
        - hostvars[groups['vpn_servers'] | first].fleet_exit_countries is defined
        - (hostvars[groups['vpn_servers'] | first].fleet_exit_countries.values() | list | community.general.counter | dictsort(by='value', reverse=true) | map('first') | first) != (ip_data.country_code | default(''))
      run_once: false
```

Look at `sources` when a single field disagreeing matters more than the vote that won — for
example, alerting when any provider flags the host as a known VPN or proxy exit, even if the
merged result does not:

```yaml
- name: Alert when any provider flags this host as a VPN/proxy exit
  ansible.builtin.debug:
    msg: "{{ item.provider }} flags this host: {{ item.data }}"
  loop: "{{ ip_data.sources | selectattr('ok') }}"
  loop_control:
    label: "{{ item.provider }}"
  when: (item.data.is_vpn | default(false)) or (item.data.is_proxy | default(false))
```

Example Playbook
----------------

```yaml
- hosts: vpn_servers
  tasks:
    - name: Work out where this host looks like it is
      ansible.builtin.include_role:
        name: get_ip_data

    - name: Refuse to deploy the exit node inside the censored country
      ansible.builtin.assert:
        that:
          - ip_data.country_code != 'RU'
        fail_msg: "{{ inventory_hostname }} egresses through {{ ip_data.country_code }} ({{ ip_data.asn_org }})"
```

One request on a healthy host, and never mind the geolocation:

```yaml
- name: Just get the public IP, cheaply
  ansible.builtin.include_role:
    name: get_ip_data
  vars:
    get_ip_data_policy: first_successful
    get_ip_data_required_fields: ['ip']
    get_ip_data_providers: ['ipify_facts', 'ipinfo_io']
```

A heavily filtered host, where being slow is fine and being wrong is not:

```yaml
- name: Collect whatever still answers
  ansible.builtin.include_role:
    name: get_ip_data
  vars:
    get_ip_data_policy: check_all
    get_ip_data_prefer_modules: false      # ask the ipinfo.io twins separately as well
    get_ip_data_timeout: 4
    get_ip_data_retries: 1
    get_ip_data_show_sources: true
    get_ip_data_fail_when_no_result: false
```

Caveats
-------

- **`ipinfoio_facts` and `ipify_facts` set host facts.** They are facts modules, so their
  payload lands in the host's variables whether you want it or not. `ipify_facts` only adds
  `ipify_public_ip`, but `ipinfoio_facts` adds `ip`, `hostname`, `city`, `region`, `country`,
  `loc`, `org`, `postal` and `timezone` at set_fact precedence, which outranks anything from
  `group_vars`. If those names carry meaning in your inventory, put `ipinfoio_facts` in
  `get_ip_data_disabled_providers`; the `ipinfo_io` HTTP twin reads the same endpoint without
  the side effect.
- **`ip_api_com` is plain HTTP.** ip-api.com answers HTTPS with `403 SSL unavailable for this
  endpoint` unless you pay. The request carries no credentials and the reply is public data,
  but disable the provider if cleartext is unacceptable where you run this.
- **Quotas are per source IP.** Running `check_all` against a fleet that shares one egress IP
  will exhaust the free daily budgets of ipapi.co and db-ip.com quickly. `first_successful` is
  the polite option for anything running on a schedule.
- **Everything here is a guess.** Free geolocation puts an IP in the right country almost
  always, the right city sometimes, and the right neighbourhood never. Trust `country_code`
  and `asn`, treat the rest as a hint.
- The role only ever looks up **the managed host's own public IP**. Looking up an arbitrary
  address is not wired through, since two of the providers cannot do it at all.

Testing
-------

```bash
ansible-playbook -i localhost, roles/get_ip_data/tests/test.yml
```

Runs both policies against the real providers and asserts they agree on the country.

License
-------

MIT

Author Information
------------------

Kenya-West
