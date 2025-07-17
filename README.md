# 🚀 Ansible Infrastructure Automation

[![Ansible](https://img.shields.io/badge/ansible-%231A1918.svg?style=for-the-badge&logo=ansible&logoColor=white)](https://www.ansible.com/)
[![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![Prometheus](https://img.shields.io/badge/Prometheus-E6522C?style=for-the-badge&logo=Prometheus&logoColor=white)](https://prometheus.io/)
[![Grafana](https://img.shields.io/badge/grafana-%23F46800.svg?style=for-the-badge&logo=grafana&logoColor=white)](https://grafana.com/)

A comprehensive Ansible automation suite for managing VPS/server infrastructure, focusing on VPN services, monitoring, backups, and security hardening.

## 🎯 Overview

This repository provides a complete infrastructure-as-code solution for setting up and managing:

- **🔧 VPS/Server Preparation**: Automated server setup with security hardening
- **🌐 VPN Infrastructure**: Complete VPN solutions with Caddy, WireGuard, and Remnawave
- **📊 Monitoring & Analytics**: Full observability stack with Prometheus, Grafana, and exporters
- **💾 Backup Solutions**: Automated backup systems using Restic and Backrest
- **🔒 Security**: UFW firewall, fail2ban, and SSH hardening
- **🛠️ Custom Toolset**: Reusable Ansible roles for common tasks

## ✨ Features

### 🏗️ Infrastructure Management
- **Server Preparation**: Automated setup of packages, Docker, shell configuration
- **Security Hardening**: SSH keys, password authentication disabling, firewall configuration
- **User Management**: Automated user creation and permission management
- **Package Management**: Support for apt, snap, and custom binary installations

### 🌍 VPN & Networking
- **VPN Servers**: WireGuard setup with Caddy as frontend reverse proxy
- **Remnawave Panel**: VPN management interface with subscription handling
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
- **Restic**: Encrypted, deduplicated backups with automation
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

```
┌─────────────────────────────────────────────────────────────────┐
│                    Ansible Control Node                        │
└─────────────────────────┬───────────────────────────────────────┘
                          │
    ┌─────────────────────┼─────────────────────┐
    │                     │                     │
    ▼                     ▼                     ▼
┌─────────┐        ┌─────────────┐        ┌─────────────┐
│VPN Node │        │Analytics    │        │Backup Node  │
│         │        │Server       │        │             │
│• Caddy  │        │             │        │• Restic     │
│• WG     │◄──────►│• Prometheus │◄──────►│• Backrest   │
│• Remna  │        │• Grafana    │        │• rclone     │
│• FRP    │        │• Victoria*  │        │• Autorestic │
└─────────┘        └─────────────┘        └─────────────┘
```

## 🚀 Quick Start

### Prerequisites

- **Ansible** 2.9+ with required collections
- **Python** 3.8+
- **SSH access** to target servers
- **sudo privileges** on target servers

### Installation

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

1. **Create inventory file**:
   ```bash
   cp inventory/production_example.ini inventory/production.ini
   # Edit inventory/production.ini with your server details
   ```

2. **Configure host variables**:
   ```bash
   # Edit files in host_vars/ and group_vars/ directories
   ```

3. **Set up SSH keys**:
   ```bash
   # Ensure your SSH key is added to target servers
   ssh-copy-id user@your-server
   ```

## 📖 Usage

### Complete Server Setup

Run the main setup playbook to prepare a server with all components:

```bash
ansible-playbook -i inventory/production.ini 0_start.yaml
```

### Targeted Operations

#### VPS Preparation
```bash
ansible-playbook -i inventory/production.ini general_vps_prepare_update.yaml
ansible-playbook -i inventory/production.ini general_vps_prepare_install_packages.yaml
```

#### VPN Setup
```bash
ansible-playbook -i inventory/production.ini install_vpn_caddy.yaml
ansible-playbook -i inventory/production.ini install_vpnremna_on_server.yaml
```

#### Monitoring Setup
```bash
ansible-playbook -i inventory/production.ini install_analytics_on_server.yaml
ansible-playbook -i inventory/production.ini install_analytics_on_node.yaml
```

#### Backup Configuration
```bash
ansible-playbook -i inventory/production.ini install_backup_restic_on_node.yaml
ansible-playbook -i inventory/production.ini install_backup_restic_on_server.yaml
```

### Limiting to Specific Hosts

```bash
ansible-playbook -i inventory/production.ini playbook.yaml --limit hostname
```

## 📋 Inventory Configuration

The inventory system supports multiple environments and server roles:

### Required Groups

- **`general_vps_prepare`**: All servers requiring basic setup
- **`vpn_caddy`**: VPN servers with Caddy frontend
- **`analytics_node`**: Servers with monitoring exporters
- **`analytics_server`**: Central monitoring server
- **`backup_restic_node`**: Servers with backup clients
- **`backup_restic_server`**: Backup storage servers

### Example Inventory

```ini
[all:vars]
ansible_user='{{ standard_user }}'
ansible_become=yes
ansible_become_method=sudo
ansible_become_pass='{{ root_password }}'

[general_vps_prepare]
vpn-server-1 ansible_host=192.168.1.100
monitoring-server ansible_host=192.168.1.101

[vpn_caddy]
vpn-server-1 ansible_host=192.168.1.100

[analytics_server]
monitoring-server ansible_host=192.168.1.101

[analytics_node]
vpn-server-1 ansible_host=192.168.1.100
```

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

## 🔧 Common Workflows

### Setting Up a New VPN Server

1. **Add server to inventory**:
   ```ini
   [general_vps_prepare]
   new-vpn-server ansible_host=YOUR_SERVER_IP
   
   [vpn_caddy]
   new-vpn-server ansible_host=YOUR_SERVER_IP
   ```

2. **Configure host variables**:
   ```bash
   # Create host_vars/new-vpn-server.yml with server-specific settings
   ```

3. **Run setup playbooks**:
   ```bash
   ansible-playbook -i inventory/production.ini 0_start.yaml --limit new-vpn-server
   ansible-playbook -i inventory/production.ini install_vpn_caddy.yaml --limit new-vpn-server
   ```

### Adding Monitoring to Existing Server

1. **Update inventory**:
   ```ini
   [analytics_node]
   existing-server ansible_host=YOUR_SERVER_IP
   ```

2. **Deploy monitoring**:
   ```bash
   ansible-playbook -i inventory/production.ini install_analytics_on_node.yaml --limit existing-server
   ```

### Setting Up Backups

1. **Configure backup variables** in `group_vars/backup_restic_node.yml`
2. **Deploy backup solution**:
   ```bash
   ansible-playbook -i inventory/production.ini install_backup_restic_on_node.yaml
   ```

## 📁 Directory Structure

```
ansible-my/
├── 0_start*.yaml                 # Main orchestration playbooks
├── general_vps_prepare_*.yaml    # Server preparation playbooks
├── install_*.yaml                # Service installation playbooks
├── remove_*.yaml                 # Service removal playbooks
├── inventory/                    # Inventory files
│   ├── production_example.ini
│   └── staging_example.ini
├── group_vars/                   # Group-specific variables
├── host_vars/                    # Host-specific variables
├── roles/                        # Ansible roles
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

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Ansible Community**: For the amazing automation platform
- **Role Contributors**: Authors of Galaxy roles used in this project
- **Open Source Projects**: All the tools and services integrated

---

**Made with ❤️ for infrastructure automation**