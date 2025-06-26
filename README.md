### Installing Ansible-lint

- `sudo apt update && sudo apt install pipx -y`
- `pipx install ansible-dev-tools`
- `pipx install ansible-lint`
- `pipx inject --include-apps ansible-lint ansible` (dunno what it does but it works. Refer to [the question on ServerFault](https://serverfault.com/a/1159621/1005795))