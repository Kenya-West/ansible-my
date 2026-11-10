configure_remnawave_panel_sync_squads
=====================================

Puts every member of a Remnawave internal squad into the external squad the
inventory maps that internal squad to, on the panel of the `vpn_server_remnawave`
host it runs against. The panel has no such rule of its own, so the role
compares and corrects on every run; schedule
`playbooks/anti_censorship/server/remnawave_sync_squads.yaml` to keep the
squads in step.

Variables
---------

Set in `inventory/group_vars/vpn_server_remnawave/squads_sync.yaml`.

| Variable | Default | Meaning |
|---|---|---|
| `vpn_server_remnawave_squads_sync` | `[]` | Rules `{internal_squad, external_squad}`, by name. A user's external squad comes from the first rule naming one of the user's internal squads. An empty `external_squad` (`''` or `null`) takes the members out of any external squad. |
| `vpn_server_remnawave_squads_sync_prune` | `ignore` | `remove` takes a user that no rule matches out of an external squad a rule names. Other external squads are never touched. |
| `vpn_server_remnawave_squads_sync_exclude_users` | the service user | Usernames that are never touched. |
| `vpn_server_remnawave_squads_sync_skip_multiple_internal_squads` | `false` | Skip users in more than one internal squad (any squads). |
| `vpn_server_remnawave_squads_sync_skip_internal_squads` | `[]` | Skip users in any of these internal squads; they must exist in the panel. |
| `vpn_server_remnawave_squads_sync_skip_user_tags` | `[]` | Skip users whose tag is one of these. |
| `vpn_server_remnawave_squads_sync_batch_size` | `500` | Users per bulk request (the panel's maximum is 500). |

The panel connection is the same as for `configure_remnawave_panel_generate_setup`:
`vpn_server_remnawave_panel_url`, `_api_token`, `_access_mode` and
`_custom_login_route_api_token`.

The four skip variables are combined with OR: a user any of them hits is not
touched, either to assign or to prune. Each run lists the skipped users that
would otherwise have moved, with the reason.

```yaml
vpn_server_remnawave_squads_sync:
  - internal_squad: Default-Squad
    external_squad: Chain-Ru-NonRu
```

How it works
------------

1. Reads the internal squads, the external squads and every user (three
   listings). If any squad a rule names is missing, it fails before writing
   anything.
2. Works out each user's target external squad. A user already in the target
   is left alone. It lists every user who will move (`name: from -> to`), and
   also lists users whose internal squads map to different external squads,
   since only the first rule can win.
3. Sends `POST /api/users/bulk/update` with `externalSquadUuid` (`null` to
   remove), one request per target squad and per 500 users. Only that field is
   sent, so internal squads and everything else on the user stay as they are.
   The panel applies the update in the background, so a listing taken right
   afterwards may still show the old squad.

`--check` sends nothing. It reports who would move and marks the report task
as changed. Running a second time changes nothing.
