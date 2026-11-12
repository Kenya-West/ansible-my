# install_docker_prune_timer

Installs `/usr/local/sbin/docker-prune.sh` plus a system-scope oneshot
`docker-prune.service` and `docker-prune.timer` (rootful Docker), weekly by
default (`Sun 04:00`, randomized up to 1h, `Persistent=true`).

Defaults mirror `playbooks/maintenance/docker_prune.yaml`: containers, images
(dangling), networks and build cache are pruned; volumes are not. Override via
`docker_prune_*` variables; `role_state: absent` removes everything.
