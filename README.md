# 🚀 Ansible Infrastructure Automation

[![Ansible](https://img.shields.io/badge/ansible-%231A1918.svg?style=for-the-badge&logo=ansible&logoColor=white)](https://www.ansible.com/)
[![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![Prometheus](https://img.shields.io/badge/Prometheus-E6522C?style=for-the-badge&logo=Prometheus&logoColor=white)](https://prometheus.io/)
[![Grafana](https://img.shields.io/badge/grafana-%23F46800.svg?style=for-the-badge&logo=grafana&logoColor=white)](https://grafana.com/)
[![VictoriaMetrics](https://img.shields.io/badge/VictoriaMetrics-442650?style=for-the-badge&logo=VictoriaMetrics&logoColor=white)](https://victoriametrics.com/)
[![VictoriaLogs](https://img.shields.io/badge/VictoriaLogs-562A65?style=for-the-badge&logo=VictoriaLogs&logoColor=white)](https://victorialogs.com/)
[![WireGuard](https://img.shields.io/badge/WireGuard-88171A?style=for-the-badge&logo=WireGuard&logoColor=white)](https://www.wireguard.com/)
[![Restic](https://img.shields.io/badge/Restic-FF5722?style=for-the-badge&logo=Restic&logoColor=white)](https://restic.net/)
[![Autorestic](https://img.shields.io/badge/Autorestic-4CAF50?style=for-the-badge&logo=Autorestic&logoColor=white)](https://autorestic.vercel.app/)
[![Caddy](https://img.shields.io/badge/Caddy-2E7D32?style=for-the-badge&logo=Caddy&logoColor=white)](https://caddyserver.com/)
[![FRP](https://img.shields.io/badge/FRP-FF5722?style=for-the-badge&logo=FRP&logoColor=white)](https://github.com/fatedier/frp)
[![Remnawave](https://img.shields.io/badge/Remnawave-3BC9DB?style=for-the-badge&logo=Remnawave&logoColor=white)](https://remna.st/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

An opinionated and comprehensive Ansible automation suite for managing VPS infrastructure, focusing on VPN services, monitoring, backups, and security hardening.

## 🖼️ Screenshots

<details>
  <summary>Click to expand</summary>
  <div align="center">

   ![Prometheus](<docs/Images/screenshot-prometheus-1.png>)
   ![Remnawave](<docs/Images/screenshot-remnawave-1.png>)
   ![VictoriaLogs](<docs/Images/screenshot-victorialogs-1.png>)
   ![Caddy](<docs/Images/screenshot-caddy-1.png>)
   ![Caddy](<docs/Images/screenshot-caddy-2.png>)
   ![Grafana](<docs/Images/screenshot-grafana-1.png>)
   ![Grafana](<docs/Images/screenshot-grafana-2.png>)
   ![Wireguard](<docs/Images/screenshot-wireguard-1.png>)

  </div>
</details>

## 📖 Terms agreements

- **VPS** = server = (control) node;
- **Central server**: a server where `analytics_server` group is deployed;
- **(Control) Node server**: a server where no `*_server` group is deployed, and where `vpn_caddy`, `analytics_node`, and `backup_restic_node` groups are deployed;
- **VPN** ≈ proxy. Sorry for this, but most of the time clients for proxies are called VPN clients and do work using TUN, mostly. So we refer to VPNs as a proxies in this project.

## 💭 Built with key concepts in mind

- VPS should be as autonomous as possible. That means:
   - No unnecessary connection should link your server;
   - Each server acts on its own, responsible for only business that runs inside the server;
   - Failure of one server should not affect others;
   - Servers should not know each other;
   - There is no central server unless it is necessary (for example, `analytics_server` group centralizes metrics gathering and only this). If necessary, it should be used only for one-direction link type, no bi-directional links allowed.

- Rely on cloud/SaaS/hosted services - popular ones, industrial standards, baked by corporations, or at least having long-term support. No unnecessary custom solutions;

- No SaaS or custom entities that cause VPS to depend on each other. That is why there is no, for example, a private CA that issues certificates - we use community's standard Let's Encrypt;

- Every VPS should be served as multi-purpose server that:
   - Has full set of necessary CLI and TUI apps for any data manipulation;
   - Is a ready-to-go platform to run Docker images;
   - Has fully-featured webserver (for our stack, it is [Caddy](https://github.com/homeall/caddy-reverse-proxy-cloudflare) based on [Lucas Lorentz' project](https://github.com/lucaslorentz/caddy-docker-proxy)) to run your apps;
   - Can act as proxy ([Remnawave](https://github.com/remnawave/panel), [FRP](https://github.com/fatedier/frp) ([dockerized](https://github.com/snowdreamtech/frp))) and a VPN ([Wireguard](https://github.com/wg-easy/wg-easy));
   - Could be able to backup itself (via [Autorestic](https://github.com/cupcakearmy/autorestic) to cloud storages or Restic server);
   - Gives you a full-picture telemetry (setup `analytics_server` first, then deploy `analytics_node`) by metrics and maybe some logs (did not test logs much);

- Every role is a modular [Ansible group](https://docs.ansible.com/ansible/2.9/modules/group_module.html), that means that you can omit or add server capabilities simply by editing your inventory files;

- Containerize everything. If you need to run something, run it in a container. Only host-level execution if it is necessary or inevitable;

- Everything should be proxied from web server. That's why even if node exporter and Docker exporter run in host, they are exposed on `172.17.0.1` IP address, which is the default Docker bridge network IP address, and then proxied by Caddy. It is a single point to control access to your services.

## 🅰️ Key style decisions for this Ansible project

- Playbooks are organized in a way that allows you to run them in any order, but they are designed to be run sequentially for a complete setup;
- All playbooks are in plain list on root of the repository;
- Roles in `kwtoolset` are designed to be reusable and can be used in any playbook.

## 📃 Requirements

Despite the approach stands for making VPS as autonomous as possible, it still needs some centralization in terms of VPN/proxying management and analytics gathering. Here are hardware requirements for all cases:

1. Central server:

- CPU: 1 core;
- RAM: 4+ GB;
- Storage: 30+ GB, SSD/NVMe preferred;
- Location: any country that is not under heavy United states sanctions provided by SDN list from OFAC. That means correct work is not guaranteed in Russia, Belarus, Iran, North Korea, Syria, Cuba, Venezuela, and other countries that are under heavy sanction pressure.

2. Node server (fully-featured: VPN, analytics, backup):

- CPU: 1 core;
- RAM: 2+ GB;
- Storage: 20+ GB;
- Location: possibly any.

## ❔ Where do I get a VPS?

Good question! I usually go with the cheapest ones that meet the requirements above. Here are some options:

- [PureServers](https://pureservers.org)
- [Rifty](https://rifty.org)
- [RHC](https://rhc.su/)

> [!NOTE]
> The developer is not affiliated with any of these services, and you should do your own research before choosing a VPS provider. It is not an offer.

## 🎯 Overview

This repository provides a complete infrastructure-as-code solution for setting up and managing:

- **🔧 VPS/Server Preparation**: Automated server setup with package installation and security hardening;
- **🌐 Web server**: Done with Caddy, can run or proxy anything;
- **🌐 VPN Infrastructure**: Complete VPN solutions with WireGuard, FRP, and Remnawave;
- **📊 Monitoring & Analytics**: Full observability stack with Prometheus, VictoriaMetrics, VictoriaLogs, Grafana, and exporters;
- **💾 Backup Solutions**: Automated backup systems using Autorestic and Backrest;
- **🔒 Security**: UFW firewall, fail2ban, and SSH hardening;
- **🛠️ Custom Toolset**: Reusable Ansible roles for common tasks.

## ✨ Features

### 🏗️ Infrastructure Management
- **Server Preparation**: Automated setup of packages, Docker, shell configuration
- **Security Hardening**: SSH keys, password authentication disabling, firewall configuration
- **User Management**: Automated user creation and permission management
- **Package Management**: Support for apt, snap, and custom binary installations

### 🌍 VPN/proxy & Networking
- **Caddy Web Server**: Reverse proxy with automatic HTTPS
- **VPN Servers**: `wg-easy` setup
- **Remnawave Panel**: VPN/proxy management interface with subscription handling
- **FRP (Fast Reverse Proxy)**: Secure tunneling and port forwarding
- **Network Security**: UFW firewall rules and fail2ban protection

### 📈 Monitoring & Analytics
- **Prometheus**: Metrics collection and alerting
- **Grafana**: Beautiful dashboards and visualization
- **VictoriaMetrics**: High-performance metrics database
- **VictoriaLogs**: Log aggregation and analysis
- **Exporters**: Node, Docker, fail2ban, and custom exporters
- **Alertmanager**: Intelligent alerting and notification routing

### 💾 Backup & Recovery
- **Autorestic**: Encrypted, deduplicated backups with automation
- **Backrest**: PostgreSQL backup solution
- **rclone**: Cloud storage synchronization
- **Automated Scheduling**: Cron-based backup execution with monitoring

### 🧰 Custom Toolset (KWToolset)
A collection of reusable Ansible roles for common tasks:
- **Container Management**: Docker Compose operations
- **File Operations**: Template-based copying and processing
- **Environment Handling**: Dotenv processing and variable management
- **Network Utilities**: Port collection and management
- **System Utilities**: Directory creation, user credentials, JSON manipulation

## 🏗️ Architecture

The complete infrastructure should be as follows:

![Complete infrastructe diagram](<docs/Images/Ansible-my scheme.drawio.svg>)

This includes:
- **Central Server** (blue) with Prometheus, Grafana, VictoriaMetrics, VictoriaLogs, and Pushgateway. Designed to be a single instance for entire infrastructure;
- **Node Servers** (on the right) with VPN, Remnawave, FRP, monitoring exporters, and backup solutions. For the simplicity sake, there is only one node server on diagram above, but you can have as many as you want;
- Outer web with you and user on the left and right sides, respectively, accessing the central server and node servers via VPN/proxy;
- Outer web services like cloud storages, used for backups.

## 🚀 Quick Start

> [!NOTE]
> This project is aimed to work on Linux. For the sake of simplicity, it is assumed that distributive is Ubuntu 24.04+.

### Prerequisites

- **Ansible** 2.9+ with required collections
- **Python** 3.8+
- **SSH access** to target servers
- **sudo privileges** on target servers

### Installation

Below is a short overview of the installation process.

Dive into [wiki](https://github.com/Kenya-West/ansible-my/wiki/Preparing-Ansible-environment) for detailed configuration steps. Here is a quick overview of what you need to do:

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Kenya-West/ansible-my.git
   cd ansible-my
   ```

2. **Install Ansible dependencies**:
   ```bash
   ansible-galaxy install -r roles/requirements.yaml
   ```

3. **Install development tools** (optional):
   ```bash
   sudo apt update && sudo apt install pipx -y
   pipx install ansible-dev-tools
   pipx install ansible-lint
   pipx inject --include-apps ansible-lint ansible
   ```

### Configuration

The configuration of this Ansible project is quite complex. It requires hundreds of variables to be set.

Luckily, [there are playbooks](https://github.com/Kenya-West/ansible-my/wiki/Initial-Configuration) that help you to set up the project the quick and simple way. Look for wiki to start with.

Dive into wiki for detailed configuration steps.

## 📖 Usage

The usage process of this Ansible project is quite complex, and because it is designed for modularity, there are several ways to run it.

Look for wiki to start with.

### General server preparation

You need to run the playbooks split in 3 steps to prepare a server with all components. [Look for wiki](https://github.com/Kenya-West/ansible-my/wiki/Run-VPS-prepare) to start with.

### Analytics node setup

TBD

### VPN/proxy setup on node server

TBD

### Backup node setup

TBD

### Central server setup

TBD

## 🎯 Project structure

Playbooks:
- In root of repo, there is a list of playbooks, dedicated to specific groups of servers:
    - `0_start_step_*.yaml`: contains automated steps to run `general_vps_prepare_*` playbooks, decomposed to smaller steps to make it easier to debug and run;
    - `general_vps_prepare_*.yaml`: the basic setup of the node, like installing packages, configuring SSH, etc. Without this playbook, you will not be able to run any other playbooks;
    - `install_vpn_caddy*.yaml`, `install_vpnremna_on_server_*.yaml`, `install_analytics_on_node*.yaml`, `install_analytics_on_server*.yaml`, `install_backup_on_node*.yaml`: playbooks that install specific services on the node and server, like VPN, analytics, and backup;

`group_vars`:
- `all/`: Variables applied to all hosts
- `all_example/`: Example global variables template
- `analytics_node/`: Variables for the analytics_node group
- `analytics_server/`: Variables for the analytics_server group
- `backup_backrest_server/`: Variables for the backup_backrest_server group
- `backup_restic_node/`: Variables for the backup_restic_node group
- `backup_restic_server/`: Variables for the backup_restic_server group
- `general_vps_prepare/`: Variables for the general_vps_prepare group
- `proxy_client/`: Variables for the proxy_client group
- `servers_with_domains/`: Variables for the servers_with_domains group
- `vpn_caddy/`: Variables for the vpn_caddy group
- `vpn_remna_server_caddy/`: Variables for the vpn_remna_server_caddy group

The `all/z_common_hosts_secrets/` contains shared variables with for all roles that are considered secrets but should be shared to every host.

`host_vars`:
- `hostname-1`: Any variables that are specific to `hostname-1` a single host can be placed in `host_vars/` directory. This allows you to define host-specific configurations without cluttering the main playbooks. `hostname-1` is a placeholder for any hostname you want to configure.

> [!NOTE]
> The directories with hostnames are ignored by git, so you can place your secrets there without worrying about them being committed to the repository.

`assets`:
Contains static files and templates that are used by the playbooks. This includes:
- `hosts-list/common` - a list of files that can be used in playbooks/roles for templating or configuration purposes. Contains files for roles:
   - `analytics_node`: directory name `analytics-node`;
   - `analytics_server`: directory name `analytics-server`;
   - `backup_restic_node`: directory name `backup-restic-node`;
   - `backup_restic_server`: directory name `backup-restic-server`;
   - `general_vps_prepare`: directory name `general-machine-prepare`;
   - `vpn_caddy`: directory name `vpn-caddy` and `web-features-caddy`;
   - `vpn_remna_server_caddy`: directory name `vpn_remna_server_caddy`;
   - `proxy_client`: directory name `proxy-client`.

You can create your own directories here and use them in your playbooks/roles in this path: `assets/hosts-list/<your-hostname>/`, e.g. `assets/hosts-list/hostname-1/`. All playbooks will pick files up automatically and template them like a `common` ones.

> [!NOTE]
> The directories with hostnames are ignored by git, so you can place your secrets there without worrying about them being committed to the repository.

## 🎯 Playbook Organization

### Main Categories

| Category | Purpose | Examples |
|----------|---------|----------|
| **`0_start*`** | Complete server setup orchestration | `0_start.yaml`, `0_start_local.yaml` |
| **`general_vps_prepare_*`** | Server preparation and hardening | `general_vps_prepare_update.yaml` |
| **`install_analytics_*`** | Monitoring and analytics setup | `install_analytics_on_server.yaml` |
| **`install_backup_*`** | Backup solution deployment | `install_backup_restic_on_node.yaml` |
| **`install_vpn_*`** | VPN infrastructure setup | `install_vpn_caddy.yaml` |
| **`install_web_*`** | Web services and features | `install_web_features_caddy.yaml` |
| **`remove_*`** | Service removal and cleanup | `remove_vpn.yaml` |

### Playbook Dependencies

The `0_start.yaml` playbook orchestrates the complete setup:

```yaml
---
- import_playbook: ./general_vps_prepare_update.yaml
- import_playbook: ./general_vps_prepare_install_packages.yaml
- import_playbook: ./general_vps_prepare_install_eget.yaml
- import_playbook: ./general_vps_prepare_install_docker.yaml
# ... and more
```

## 🧰 KWToolset - Custom Utility Roles

The `roles/kwtoolset/` directory contains reusable utility roles:

### Container Management
- **`container_up`**: Start Docker Compose services
- **`container_stop_down`**: Stop and remove containers
- **`container_pull`**: Pull container images

### File Operations
- **`copy_files`**: Basic file copying
- **`copy_files_templating`**: Template-based file copying with variable substitution
- **`copy_files_dumb`**: Simple file copying without templating

### System Utilities
- **`create_dirs`**: Directory creation with permissions
- **`collect_ports`**: Network port collection and management
- **`collect_ports_range`**: Port range management
- **`envsubst_files`**: Environment variable substitution
- **`load_dotenv_to_facts`**: Load environment variables from .env files

### Data Processing
- **`modify_json_file`**: JSON file manipulation
- **`sanitize_dotenv`**: Environment file sanitization
- **`get_strings_from_file`**: Extract strings from files
- **`user_credentials_from_dotenv_to_dict`**: Process user credentials

### Archive Operations
- **`unzip`**: File extraction utilities

## 📁 Directory Structure

It is a standard Ansible project structure with a few customizations to fit the project's needs. Here is an overview of the directory structure:

```
ansible-my/
├── *.yaml                        # Playbooks
├── action_plugins/               # Python action plugins
├── inventory/                    # Inventory files
│   ├── production_example.ini
│   └── staging_example.ini
├── group_vars/                   # Group-specific variables
├── host_vars/                    # Host-specific variables
├── roles/                        # Ansible custom roles
│   ├── kwtoolset/               # Custom utility roles
│   ├── install_*/               # Installation roles
│   └── requirements.yaml        # Role dependencies
├── assets/                       # Static files and templates
├── scripts/                      # Utility scripts
└── ansible.cfg                   # Ansible configuration
```

## 🔒 Security Features

- **SSH Key Management**: Automated SSH key deployment
- **Password Authentication**: Disable password-based auth
- **Firewall Configuration**: UFW rules with sensible defaults
- **Fail2ban**: Intrusion prevention system
- **User Management**: Secure user creation and sudo configuration
- **SSL/TLS**: Automated certificate management with Certbot

## 📊 Monitoring Stack

### Components
- **Prometheus**: Metrics collection and storage
- **Grafana**: Visualization and dashboards
- **VictoriaMetrics**: High-performance metrics database
- **VictoriaLogs**: Log aggregation and analysis
- **Alertmanager**: Alert routing and notification
- **Blackbox Exporter**: Endpoint monitoring
- **Node Exporter**: System metrics
- **Docker Exporter**: Container metrics
- **Fail2ban Exporter**: Security metrics

### Monitoring Workflow
1. **Deploy analytics server**: Central monitoring hub
2. **Install node exporters**: On all monitored servers
3. **Configure Prometheus**: Automatic target discovery
4. **Set up dashboards**: Pre-configured Grafana dashboards
5. **Configure alerting**: Intelligent alert routing

## 💾 Backup Strategy

### Restic Backup Features
- **Encryption**: All backups are encrypted
- **Deduplication**: Efficient storage usage
- **Compression**: Reduced backup sizes
- **Incremental**: Only changed data is backed up
- **Automated**: Cron-based scheduling
- **Monitoring**: Backup job monitoring via Prometheus

### Backup Workflow
1. **Configure storage**: Set up backup repositories
2. **Deploy backup client**: Install on target servers
3. **Schedule backups**: Automated cron jobs
4. **Monitor backups**: Integration with monitoring stack
5. **Test restoration**: Regular restore testing

## 🤝 Contributing

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/amazing-feature`
3. **Make your changes**
4. **Test thoroughly**: Ensure playbooks work as expected
5. **Commit changes**: `git commit -m 'Add amazing feature'`
6. **Push to branch**: `git push origin feature/amazing-feature`
7. **Open a Pull Request**

### Development Guidelines

- **Follow Ansible best practices**
- **Use meaningful variable names**
- **Add comments for complex logic**
- **Test on multiple environments**
- **Update documentation**

## 📚 Roadmap

- **Make roles idempotent**: Ensure all roles can be run multiple times without side effects. For example, there are multiple `ansible.builtin.shell` tasks that do not really check if teh action needs to be performed or not;
- **Publish reusable roles**: Extract common functionality into reusable roles for the Ansible Galaxy;
- **Improve documentation**: Add more examples and usage scenarios;
- **Avoid naming conflicts**: Ensure that role names and variable names do not conflict with existing Ansible Galaxy roles and own codebase. That means to add prefixes to roles and variables, e.g. `kwtoolset_` for custom roles.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Ansible Community**: For the amazing automation platform
- **Role Contributors**: Authors of Galaxy roles used in this project
- **Open Source Projects**: All the tools and services integrated

Especially:
- [geerlingguy](https://github.com/geerlingguy) for his multiple Ansible for DevOps repos;
- [darkwizard242](https://github.com/darkwizard242) for making dense Ansible roles that are used in this project;
- [devsec](https://github.com/dev-sec) for his [Ansible Security Hardening](https://github.com/dev-sec/ansible-collection-hardening);
- [Oefenweb](https://github.com/Oefenweb) for [ansible-fail2ban](https://github.com/Oefenweb/ansible-fail2ban);
- Author of [template_tree](https://github.com/geluk/template_tree) script that is heavily used in this project to template and copy files;
- [fatedier](https://github.com/fatedier) for his work on [FRP](https://github.com/fatedier/frp), which is used for proxying and tunneling in this project, and [snowdreamtech](https://github.com/snowdreamtech) for [dockerized FRP](https://github.com/snowdreamtech/frp);
- Maintainers of [wg-easy](https://github.com/wg-easy/wg-easy), one of the simplest and most user-friendly WireGuard VPN solutions available, which is used in this project for VPN management;
- Authors of [Caddy](https://github.com/caddyserver/caddy), a powerful, enterprise-ready, open-source web server with automatic HTTPS written in Go. [Lucas Lorentz' project](https://github.com/lucaslorentz/caddy-docker-proxy) and [him](https://github.com/lucaslorentz) for his work on Caddy reverse proxy with Docker support. [HomeAll](https://github.com/homeall/caddy-reverse-proxy-cloudflare) for their work on Caddy reverse proxy with Cloudflare support and making it the most powerful Caddy setup across GitHub!
- [Remnawave](https://github.com/Remnawave) maintainer for [the best VPN/proxy management panel](https://github.com/Remnawave/panel) available designed for scalability. Their [community](https://remna.st/docs/awesome-remnawave/) is very active and helpful, so you can always ask for help if you have any issues with the panel. Also [Jolymmiels](https://github.com/Jolymmiels) for his [Telegram shop bot](https://github.com/Jolymmiels/remnawave-telegram-shop), [maposia](https://github.com/maposia) for his [Telegram miniapp](https://github.com/maposia/remnawave-telegram-sub-mini-app) to view susbcription in the messenger, [legiz](https://github.com/legiz-ru) for [custom pages templates](https://github.com/legiz-ru/my-remnawave), [SmallPoppa](https://github.com/SmallPoppa) for design of [HTML fallback static pages](https://github.com/SmallPoppa/sni-templates);
- And many more contributors and maintainers of open source projects that make this project possible! Open PR to add your name here if you think you deserve it!

---

**Made with ❤️ for infrastructure automation**