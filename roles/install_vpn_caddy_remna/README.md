install_vpn_caddy_remna
=======================

Deploys the Remnawave node (`remnawave/node`, container `remna`) of a
`vpn_caddy` host as a Compose project:
- It joins the `caddy` network, where its REALITY target lives: Caddy, or the
  nginx cover in front of it (`roles/install_vpn_caddy_caddy`, "Cover").
- It joins the internal `warp` network, where MicroWARP answers as
  `microwarp-socks`.
- It publishes 443 (unless Caddy owns it) and the control port, which UFW
  opens to the panel's IPs only.
- It optionally gets an **egress interface**: a second address of the same
  machine for everything the node sends out.

`playbooks/anti_censorship/node/remna.yaml` runs it after
`kwtoolset/resolve_host_relations`, which finds the panel the node registers
with.

Egress interface
----------------

A machine with two addresses on two interfaces counts as two hops. Clients and
upstream nodes connect to `ansible_host` (the DNS records stay as they are),
and whatever the node opens itself leaves through the other interface's
address: the next hop, the sites of the exit, everything. Only the node
container is routed that way; the host and every other container keep the
main routing table. No address is written anywhere: an interface name, an
address family and, rarely, a gateway.

```yaml
# host_vars/<node>/vpn_caddy/remna.yaml
remna_node_hops:
  egress:
    interface: ens4    # the interface of the second address
    family: ipv4       # ipv4 | ipv6 | dual
    gateway: auto      # auto, or that interface's gateway when nothing tells it
```

### How

1. **Network.** The container gets a Docker network of its own, `remna-egress`
   (bridge `br-remna-eg`, `10.247.241.0/29`, plus a ULA `/64` for
   ipv6/dual). It is attached with `gw_priority: 1`, so it is the container's
   default route; `caddy` and `warp` stay attached for what they reach.
2. **Marks.** nft table `inet remna_egress`, prerouting:
   - A connection the container opens through that bridge gets conntrack mark
     `0x2401`.
   - Packets of marked connections coming from any bridge get firewall mark
     `0x2401`.
3. **Routing.** `ip rule fwmark 0x2401 lookup 2401`, then
   `fwmark 0x2401 unreachable`. Table 2401 holds only the interface's connected
   prefixes and `default via <gateway> dev <interface>`. Docker's own
   MASQUERADE gives the packets that interface's address.
4. **Replies.** They come back on the interface, and the main table delivers
   them to the container; reverse-path filtering is loose
   (`rp_filter=2`) on that interface and on the bridge, since the main table
   routes their sources elsewhere.
5. **Inbound.** Clients connect to `ansible_host` as before: those connections
   carry no mark and answer through the main table. A connection arriving
   on the egress address (published ports listen on every address) is marked
   in forward, so its replies leave through the same interface.

The gateway is, in order:
1. the explicit `gateway`;
2. a default route of that interface in any table (a second NIC usually has
   one with a higher metric);
3. its systemd-networkd or dhclient lease;
4. its IPv6 router advertisement;
5. the link itself when it is point-to-point.

### Failing closed

The point is never to show the entry address, so every way it can go wrong
blocks instead of leaking:

- A mark finding no route (no gateway, interface down, routes flushed) hits
  the `unreachable` rule; it never falls back to the main table.
- A forward guard drops anything the container opens through its bridge
  that would leave through another interface. A second guard drops
  anything opened from the container's addresses on its other networks: that
  covers a default route that moved off the egress network.
- `remna-egress check` stops the container when its default route is not the
  egress network, or it is not attached to it. Docker reconnects containers
  *without* their `gw_priority` when a network is recreated.
- At boot `remna-egress.service` runs before Docker (`prepare`, which never
  asks Docker), so the container's first packet is already routed.
- `remna-egress.timer` runs `remna-egress-heal.service` (`apply`, after
  Docker) every 60 s. A `networkd-dispatcher` hook runs it at once when
  systemd-networkd reconfigures a link, which removes rules it did not make.
  The heal service puts everything back, refreshes the guard of the
  container's other addresses, and checks.

Everything above was tested on a lab node: Ubuntu 24.04 with systemd and
docker-ce 29, two uplinks. The ways it was broken:
- deleted routes;
- flushed rules;
- strict rp_filter;
- a changed gateway;
- the egress network reconnected without `gw_priority`;
- a reboot.

All of them blocked or healed without a packet leaving through the entry
address.

One gap remains: deleting only the `inet remna_egress` nft table lets the
container leave through the main route until the next heal (60 s). A whole
`nft flush ruleset` also removes Docker's NAT on iptables-nft hosts (Ubuntu's
default), so nothing leaves with the host's address then.

### Deploying

`tasks/egress.yml` runs before the compose and asserts these preconditions:
- Docker Engine 28+ and Compose 2.33+ (for `gw_priority`);
- the interface exists with an address of the family;
- the subnets overlap nothing the host routes;
- the `caddy` network has no IPv6, or it would become the container's IPv6
  way out.

It then creates the network, recreating it only when its settings changed and
with the compose down first. It installs:
- `/usr/local/sbin/remna-egress`;
- the units and the timer;
- `/etc/sysctl.d/95-remna-egress.conf`;
- the dispatcher hook.

Finally it runs `remna-egress prepare`.

`tasks/egress_verify.yml` runs after the compose:
1. It recreates the container when the egress network is missing or not its
   default route. `compose restart` never attaches a new network, and
   `compose up` does not notice a lost `gw_priority`.
2. It runs `remna-egress apply` and starts the timer.
3. It asks Cloudflare's trace by IP literal, from inside the container's
   network namespace and from the host. The two addresses must differ.
   The success message names both, and says when the egress address sits
   behind the provider's NAT.

Unsetting `egress` removes all of it (`tasks/egress_remove.yml`) once the
compose is up without the network.

By hand on the node:

```sh
sudo remna-egress check    # what is missing; stops the container if it would leak
sudo remna-egress apply    # put everything back
sudo nsenter -t "$(docker inspect -f '{{.State.Pid}}' remna)" -n curl -s https://1.1.1.1/cdn-cgi/trace | grep ip=
```

### IPv6

- With `family: ipv6` or `dual`, the network gets its ULA subnet, and IPv6
  leaves through the interface the same way.
- `group_vars/general_vps_prepare/secure.yaml` then turns
  `net.ipv6.conf.all.forwarding` on for that host only. os_hardening keeps it
  off everywhere else, and `apply` re-asserts it.
- `accept_ra` is raised from 1 to 2 where it is 1, so a host still learning
  its route from router advertisements keeps it once forwarding is on.
- `ipv6` alone suits only an exit. The panel refuses it on a node forwarding
  to other nodes, whose domains have IPv4 records only.
- IPv6 was not part of the lab.

Variables
---------

| Variable | Default | Meaning |
| --- | --- | --- |
| `remna_node_hops.egress.interface` | | The egress interface; unset, there is none |
| `remna_node_hops.egress.family` | `ipv4` | `ipv4`, `ipv6` or `dual` |
| `remna_node_hops.egress.gateway` | `auto` | Explicit gateway, when nothing on the host tells it |
| `remna_node_egress_network` / `_bridge` | `remna-egress` / `br-remna-eg` | Docker network and bridge name |
| `remna_node_egress_subnet_ipv4` / `_ipv6` | `10.247.241.0/29` / `fd52:656d:6e61:2401::/64` | Its subnets; must overlap nothing the host routes |
| `remna_node_egress_mark` / `_table` / `_rule_priority` | `9217` (0x2401) / `2401` / `2401` | Firewall mark, routing table, ip rule priorities (and the next one) |
| `remna_node_egress_heal_interval` | `60s` | How often everything is put back and checked |
| `remna_node_egress_probe_url_ipv4` / `_ipv6` | Cloudflare trace by IP | Asked after deploying to see the addresses |

`remna_node_hops.from`, `hidden` and `publish_direct` are the panel's: see
`roles/configure_remnawave_panel_generate_setup/README.md`, Hops between
nodes.

License
-------

BSD

Author Information
------------------

Kenya-West
