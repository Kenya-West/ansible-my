install_ufw_docker
==================

Makes Docker published ports obey UFW with [ufw-docker](https://github.com/chaifeng/ufw-docker) and keeps
the rules in sync with running containers with
[ufw-docker-automated](https://github.com/shinebayar-g/ufw-docker-automated), run as a systemd service.

What it does:

1. Installs `ufw-docker` (raw script of the master branch, the repo has no release assets) and the
   `ufw-docker-automated` release binary to `/usr/local/bin` with `copy_eget_binaries_from_controller`: eget
   downloads them on the controller and they are synchronized to the host. Only binaries missing on the
   host are installed, existing ones are never replaced.
2. Runs `ufw-docker install`, which adds the DOCKER-USER rules to `/etc/ufw/after.rules` and `after6.rules`
   (with a backup), then restarts UFW. Nothing is touched if the rules are already there.
3. Installs and starts `ufw-docker-automated.service` through `0x0I.systemd`.

Requirements
------------

Must run with `become: true`: it edits `/etc/ufw`, restarts UFW and the service runs as root.
Active UFW and Docker must already be on the host, the role asserts it. The controller needs `rsync` and
`EGET_GITHUB_TOKEN` (`github_api_token_eget`).

Behavior to know about
----------------------

After the rules are installed, **published container ports are no longer reachable from outside** unless the
container allows them. Label the container (compose `labels:`), for example:

    UFW_MANAGED: "TRUE"

See the ufw-docker-automated README for `UFW_ALLOW_FROM` and the outbound labels. Do this before running
the role on a host that serves traffic from containers.

Role Variables
--------------

See [defaults/main.yml](defaults/main.yml). The ones you will likely change:

- `ufw_docker_url`: where to download the chaifeng/ufw-docker script from, put a tag in it to pin a version.
- `ufw_docker_install_args`: extra arguments for `ufw-docker install`, e.g. `--docker-subnets`.

Tags: `install_binaries`, `install_rules`, `install_systemd_service`.
To update a binary, delete it on the host and run the playbook again.

Example Playbook
----------------

See [playbooks/networking/ufw_docker.yaml](../../playbooks/networking/ufw_docker.yaml).

Dependencies
------------

`0x0I.systemd` (roles/requirements.yaml).
