install_vpn_caddy_caddy
=======================

Deploys Caddy (`homeall/caddy-reverse-proxy-cloudflare`, container `caddy`) as
the web server of a host of the `caddy` group: it builds its sites from the
`caddy*` labels of the containers on the `caddy` Docker network, obtains their
certificates and serves the fake site of a Remnawave node
(`static/sni-templates/current`). `playbooks/reverse_proxy/caddy.yaml` runs it.

On a Remnawave node it also deploys the **cover**: an nginx container that
answers the outside world in Caddy's place.

Cover
-----

A node's port 443 belongs to Xray. REALITY forwards every connection that is
not one of its clients to its `target`, so whoever probes the node talks to
that target's TLS stack, and REALITY shapes its own handshakes after it. With
Caddy as the target that stack is Go's `crypto/tls`, which differs from the
nginx/OpenSSL most sites run:

| Seen from outside | Caddy (Go) | nginx (OpenSSL) |
|---|---|---|
| TLS 1.3 session tickets | 1, before the client's Finished | 2, after it |
| A client preferring AES-256 | gets AES-128 anyway | gets AES-256 |
| TLS 1.2 ServerHello extensions | `35-65281-23-16-11-0` | `65281-0-11-35-16-23` |
| HTTP/2 SETTINGS | 250 streams, 1 MiB window | 128 streams, 64 KiB window |
| Headers | `Server: Caddy`, `Alt-Svc: h3`, empty 404 | `Server: nginx/…`, HTML 404 |

The cover (`caddy_cover_*`, container `cover`, `nginx:stable-alpine-slim`) is
a second service of this role's Compose project. Caddy is untouched behind it:
it keeps the labels, the routing and the certificates.

```
:443 → remna (Xray REALITY) ── not a client ──▶ cover:443
:80  ───────────────────────────────────────▶ cover:80

cover:443, by the ClientHello alone (nothing is decrypted yet):
  ALPN acme-tls/1 ............................ Caddy, raw TLS (TLS-ALPN-01)
  a name without a certificate copy yet ....... Caddy, raw TLS
  caddy_cover_passthrough_names ............... Caddy, raw TLS
  anything else ............................... nginx terminates TLS:
      a cover name ............ the fake site, served by nginx itself
        /internal-network/* ... handed to Caddy (exporters, autodiscovery)
      another name of Caddy ... handed to Caddy as it is
      no or an unknown name ... caddy_cover_unknown_sni

cover:80: 301 to https, except /.well-known/acme-challenge/ (Caddy, HTTP-01)
```

The cover names are `domains_keys.main`, `main_extra` and the domains of
`domains_keys.remna_node`. Every other name Caddy has a certificate for is
terminated by nginx too and proxied to Caddy over the `caddy` network, so no
name of the host shows Go's TLS on port 443.

### Certificates

nginx never talks to an ACME server. It reads what
`install_webfeatures_certcopy` copies out of Caddy every night into
`cert_location_root_path` (`/etc/ssl/shared/<name>/fullchain.pem` and
`privkey.pem`, world-readable as that role leaves them). The paths carry a
variable, so nginx reads them at the handshake and a renewed certificate needs
no reload.

Which names nginx answers is decided when the role runs, from the certificates
present at that moment (`tasks/cover.yml` runs the certcopy helper first). A
name without a copy yet keeps going to Caddy as raw TLS, and with no cover
name copied at all the cover hands everything to Caddy, exactly as before it
existed. That is the state of a fresh node: Caddy has no certificates when
`caddy.yaml` runs. `playbooks/reverse_proxy/cover.yaml`, imported after
`certcopy.yaml` in the scenarios, waits up to two minutes for them and
re-reads; so does any later run of `caddy.yaml`. The last task of both prints
who answers what.

A name of `domains_keys` that has no certificate yet is passed to Caddy, so a
service deployed later works at once. A name the inventory did not know at the
last run does not: behind REALITY it meets the default certificate until one
of the two playbooks has run again.

### Rolling it out

`vpn_server_remnawave_config_profiles_reality_target` is one value for every
node of a panel, and a node whose target does not resolve accepts no client.
Hence the alias: the name `cover` (`caddy_cover_alias`) belongs to the cover
container where there is one and to Caddy where there is none.

1. Run `playbooks/reverse_proxy/caddy.yaml` on every node. Each gets the alias
   and, with `caddy_cover_enabled`, the cover; port 80 moves to nginx. Caddy is
   recreated once (a few seconds). REALITY still targets `caddy:443`.
2. Set `vpn_server_remnawave_config_profiles_reality_target: cover:443` and run
   the panel playbook. Not before step 1 is done on **all** nodes.
3. Check a node from outside: `curl -sI https://<a node domain>/` answers
   `server: nginx/…`, and so does `curl -sI http://<a node domain>/` with a 301.

`caddy_cover_enabled: false` in a node's host_vars takes its cover away again
on the next untagged (or `update_config_hard`) run of `caddy.yaml`: the
container is removed, Caddy publishes port 80 and carries the alias.

### Variables

| Variable | Default | |
|---|---|---|
| `caddy_cover_enabled` | `true` | Never active with `caddy_occupy_HTTPS` or `caddy_http_only` |
| `caddy_cover_alias` | `cover` | The host name of REALITY's target |
| `caddy_cover_unknown_sni` | `cert` | `cert`: first cover name's certificate and the fake site, as a stock nginx; `reject`: refuse the handshake, as Caddy did |
| `caddy_cover_passthrough_names` | `[]` | Names left to Caddy's own TLS, e.g. a gRPC service |
| `caddy_cover_names` | main, main_extra, remna_node domains | Names nginx serves the fake site for |
| `caddy_cover_image` | `nginx:stable-alpine-slim` | |
| `caddy_cover_wait_for_certs` | `0` (`cover.yaml`: 120) | Seconds to wait for the cover names' certificates |

Tags: the cover is prepared and reloaded with `update_config_hard`,
`update_config_soft` and `caddy_cover`. Like any change of the Compose file,
turning it on or off needs an untagged or `update_config_hard` run.

### Limits

- Caddy's sites on other published ports (`caddy_external_ports_allowlist`,
  e.g. the frp dashboard port) are still Caddy's own TLS.
- nginx speaks HTTP/1.1 to Caddy: gRPC behind REALITY needs
  `caddy_cover_passthrough_names`.
- Caddy logs the cover's address as the client of what nginx hands it. It
  logged the node container's before: REALITY passes no client address
  (`xver: 0`).
- HTTP/3 is off in Caddy (`servers { protocols h1 h2 }` in the Caddyfile): no
  UDP port is published, and Caddy announced it in `Alt-Svc` regardless.
