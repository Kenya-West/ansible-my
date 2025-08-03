# General VPS Prepare Group

**The Foundation of Your Infrastructure Automation**

The `General VPS Prepare` group is the cornerstone of the ansible-my infrastructure automation suite. It transforms a fresh, minimal VPS into a fully-equipped, secure, and production-ready server platform that serves as the foundation for all other specialized roles and services.

## 🎯 Purpose and Design Philosophy

The `General VPS Prepare` group embodies the project's core principle of creating **autonomous, self-sufficient servers**. Each VPS is transformed into a multi-purpose platform that can:

- Function independently without requiring connections to other servers
- Serve as a ready-to-go Docker platform for containerized applications
- Provide a comprehensive development and administration environment
- Maintain security best practices from the ground up
- Support specialized roles like VPN services, monitoring, and backup solutions

## 🚀 What This Role Accomplishes

### Core Transformation Goals

1. **🔧 Foundation Setup**: Converts a basic VPS into a fully-featured server platform
2. **🔒 Security Hardening**: Implements multiple layers of security protection
3. **🛠️ Developer Experience**: Provides modern CLI tools and enhanced shell environment
4. **🐳 Container Readiness**: Sets up Docker platform for application deployment
5. **📊 Monitoring Readiness**: Configures metrics endpoints for observability
6. **🎛️ System Optimization**: Tunes system settings for performance and reliability

## 📦 Comprehensive Package Installation

### System Foundation Packages

The role installs essential system packages via APT:

**Base System Tools:**
- `bash`, `curl`, `wget`, `unzip` - Core utilities
- `ncdu`, `tree`, `lsof`, `net-tools` - System analysis tools
- `gpg`, `gettext-base`, `acl` - Security and permissions
- `rsync`, `bc`, `moreutils` - Data synchronization and utilities
- `locales`, `snapd`, `cron` - System services

**Python Dependencies for Ansible:**
- `python3-docker` - [Docker module support](https://docs.ansible.com/ansible/latest/collections/community/docker/)
- `python3-passlib` - [Password hashing](https://pypi.org/project/passlib/)
- `python3-bcrypt` - [Encryption support](https://pypi.org/project/bcrypt/)

**Modern System Utilities:**
- [`neofetch`](https://github.com/dylanaraps/neofetch) - System information display
- [`bat`](https://github.com/sharkdp/bat) - Enhanced `cat` with syntax highlighting
- [`fd-find`](https://github.com/sharkdp/fd) - Modern `find` replacement
- [`httpie`](https://github.com/httpie/httpie) - Human-friendly HTTP client
- [`hstr`](https://github.com/dvorka/hstr) - Bash history suggest box
- [`duf`](https://github.com/muesli/duf) - Modern `df` replacement
- [`jq`](https://github.com/jqlang/jq) - JSON processor
- [`ripgrep`](https://github.com/BurntSushi/ripgrep) - Fast text search
- [`micro`](https://github.com/zyedidia/micro) - Modern terminal text editor
- [`btop`](https://github.com/aristocratos/btop) - Resource monitor
- [`sqlite3`](https://www.sqlite.org/) - Database engine
- [`nala`](https://github.com/volitank/nala) - Enhanced APT frontend
- [`doas`](https://github.com/Duncaen/OpenDoas) - Lightweight sudo alternative

**Snap Packages:**
- [`procs`](https://github.com/dalance/procs) - Modern `ps` replacement
- [`trippy`](https://github.com/fujiapple852/trippy) - Network diagnostic tool

### Additional Package Managers

**Deb-get Integration:**
- [`deb-get`](https://github.com/wimpysworld/deb-get) - Automated .deb package installation
- GitHub API token integration for enhanced rate limits
- Additional packages installed via deb-get:
  - [`powershell`](https://github.com/PowerShell/PowerShell) - Cross-platform PowerShell
  - [`zenith`](https://github.com/bvaisvil/zenith) - System monitor with zoom capabilities

The role uses [`eget`](https://github.com/zyedidia/eget) to install the latest versions of modern CLI tools directly from GitHub releases:

**NOTE:** The role includes [`debget`](https://github.com/wimpysworld/deb-get) installation as a prerequisite for deb-get functionality.

**File and Directory Management:**
- [`eza`](https://github.com/eza-community/eza) - Modern `ls` replacement with icons and git integration
- [`erdtree`](https://github.com/solidiquis/erdtree) - Multi-threaded file-tree visualizer
- [`otree`](https://github.com/fioncat/otree) - Command-line file tree display
- [`broot`](https://dystroy.org/broot/) - Interactive directory tree viewer
- [`dua-cli`](https://github.com/Byron/dua-cli) - Disk usage analyzer
- [`gomi`](https://github.com/babarot/gomi) - Safe rm with trash functionality

**Development and Git Tools:**
- [`fzf`](https://github.com/junegunn/fzf) - Fuzzy finder for command-line
- [`lazydocker`](https://github.com/jesseduffield/lazydocker) - Docker management TUI
- [`lazygit`](https://github.com/jesseduffield/lazygit) - Git management TUI
- [`gitui`](https://github.com/extrawurst/gitui) - Fast terminal UI for git

**Data Processing and Analysis:**
- [`yq`](https://github.com/mikefarah/yq) - YAML/JSON/XML processor
- [`jl`](https://github.com/koenbollen/jl) - JSON log viewer
- [`jless`](https://github.com/PaulJuliusMartinez/jless) - Command-line JSON viewer
- [`gron`](https://github.com/tomnomnom/gron) - JSON grep tool
- [`xan`](https://github.com/medialab/xan) - CSV/TSV data toolkit

**Network and System Utilities:**
- [`xh`](https://github.com/ducaale/xh) - HTTP client (HTTPie-like)
- [`gping`](https://github.com/orf/gping) - Ping with graph visualization
- [`doggo`](https://github.com/mr-karan/doggo) - DNS lookup tool
- [`pping`](https://github.com/wzv5/pping) - Pretty ping tool

**Log and Text Processing:**
- [`lnav`](https://github.com/tstack/lnav) - Log file navigator and analyzer
- [`lazyjournal`](https://github.com/Lifailon/lazyjournal) - Systemd journal viewer
- [`tailspin`](https://github.com/bensadeh/tailspin) - Log file highlighter
- [`riff`](https://github.com/walles/riff) - Diff tool with syntax highlighting
- [`loggo`](https://github.com/aurc/loggo) - Log aggregation tool

**File Transfer and Backup:**
- [`termscp`](https://github.com/veeso/termscp) - Terminal file transfer client
- [`rclone`](https://rclone.org/) - Cloud storage synchronization
- [`autorestic`](https://github.com/cupcakearmy/autorestic) - Backup automation wrapper for restic

**System Administration:**
- [`killport`](https://github.com/jkfran/killport) - Kill processes by port
- [`systemctl-tui`](https://github.com/rgwood/systemctl-tui) - Systemd service management TUI
- [`tufw`](https://github.com/peltho/tufw) - UFW firewall management TUI
- [`wait4x`](https://github.com/wait4x/wait4x) - Wait for various conditions
- [`zoxide`](https://github.com/ajeetdsouza/zoxide) - Smart cd command
- [`isd`](https://github.com/isd-project/isd) - System information tool

### Shell and Terminal Enhancement

**Oh My Posh:**
- [`Oh My Posh`](https://github.com/JanDeDobbeleer/oh-my-posh) - Cross-platform prompt theme engine
- Default theme: `illusi0n` for bash, `jandedobbeleer` for PowerShell
- Custom bash profiles with enhanced functionality and modern features
- PowerShell profile configuration with advanced prompt customization

**PowerShell Integration:**
- [`PowerShell Core`](https://github.com/PowerShell/PowerShell) - Cross-platform PowerShell
- PowerShell modules via PowerShell Gallery:
  - [`PSReadline`](https://github.com/PowerShell/PSReadLine) - Enhanced command-line editing
  - [`PSScriptTools`](https://github.com/jdhitsolutions/PSScriptTools) - PowerShell scripting utilities
  - [`posh-git`](https://github.com/dahlbyk/posh-git) - Git integration for PowerShell
  - [`PSFzf`](https://github.com/kelleyma49/PSFzf) - Fuzzy finder integration
- PowerShell profile setup with custom functions and aliases

## 🐳 Docker Platform Setup

The role establishes a complete Docker platform:

**Docker Installation and Configuration:**
- Latest Docker Engine from official repositories
- Docker daemon configuration with metrics enabled
- User permissions for Docker operations
- Docker service optimization

**Docker Mirrors and Optimization:**
- Regional mirror configuration (especially for RU region)
- Registry mirrors: Timeweb Cloud, Mirror GCR, DaoCloud, 163.com
- Performance optimization settings
- Metrics endpoint exposure on `172.17.0.1:9323`

**Docker Features:**
- Containerd snapshotter enabled
- Metrics collection configured
- Service health monitoring
- Automatic service restart and verification

## 🔒 Security Features

### SSH Hardening

The role implements comprehensive SSH security using the [`devsec.hardening.ssh_hardening`](https://github.com/dev-sec/ansible-collection-hardening) collection:

- **Root Login**: Restricted to key-based authentication only (`without-password`)
- **Password Authentication**: Completely disabled for all users
- **Authentication Methods**: Limited to public key authentication only
- **User Access Control**: Explicitly defined allowed users list
- **Port Configuration**: Custom SSH port management

### Operating System Hardening

Using [`devsec.hardening.os_hardening`](https://github.com/dev-sec/ansible-collection-hardening):

- **Filesystem Security**: Whitelist configuration (includes squashfs for Snap support)
- **User Security**: Controlled user permissions and access
- **Network Security**: IPv4 forwarding enabled for container networking
- **System Optimization**: Security-focused kernel parameter tuning
- **Password Aging**: Configurable password policies

### Intrusion Prevention

**Fail2ban Configuration:**
- [`oefenweb.fail2ban`](https://github.com/Oefenweb/ansible-fail2ban) role implementation
- Systemd backend integration
- Automated IP banning for suspicious activities
- Custom jail configurations
- Log monitoring and alerting

### User Management and Access Control

**User Administration:**
- Automated user creation with proper permissions
- SSH key deployment and management
- Sudo access configuration
- Home directory setup with proper permissions
- Shell configuration for enhanced user experience

## 🛠️ System Configuration and Optimization

### Locale and Internationalization
- System locale configuration
- UTF-8 encoding setup
- Timezone management
- Regional settings optimization

### Logging and Journal Management
- Systemd journal configuration
- Log rotation policies
- Persistent logging setup
- Journal cleanup and optimization

### Performance Optimization
- System cache management and cleanup
- Service optimization
- Resource allocation tuning
- Network stack optimization

### Default Editor Configuration
- Micro text editor as system default
- Enhanced editing experience
- Syntax highlighting and plugins
- User-friendly keybindings

### Configuration Templates and Files

The role deploys comprehensive configuration files for installed tools:

**Application Configurations:**
- **Micro Editor**: Enhanced configuration with plugins and keybindings
- **Doas**: Lightweight sudo alternative configuration for secure privilege escalation
- **Broot**: Directory tree viewer configuration with custom shortcuts
- **Bash**: Enhanced bash profile with modern aliases and functions
- **PowerShell**: Custom PowerShell profile with module integration and prompt customization

**Template Assets:**
- Configuration templates located in `assets/hosts-list/common/general-machine-prepare/`
- Customizable per-host configurations in `assets/hosts-list/<hostname>/`
- Git-ignored host-specific directories for sensitive configurations

## 📊 Monitoring and Observability Ready

The role prepares the system for comprehensive monitoring:

**Metrics Endpoints:**
- Docker metrics on port 9323
- System metrics collection ready
- Service health monitoring
- Performance metric exposure

**Integration Points:**
- Ready for Prometheus integration
- Grafana dashboard compatibility
- VictoriaMetrics support
- Log aggregation preparation

## 🎯 Usage Instructions

### Prerequisites

Before running the General VPS Prepare playbooks, ensure:

1. **Fresh VPS**: Ubuntu 24.04+ recommended
2. **SSH Access**: Root access or sudo user with SSH key authentication
3. **Network Access**: Internet connectivity for package downloads
4. **Ansible Setup**: Ansible 2.9+ with required collections

### Basic Usage

1. **Add your server to inventory** with the `general_vps_prepare` group:
```ini
[general_vps_prepare]
your-server-hostname ansible_host=YOUR_SERVER_IP
```

2. **Run the complete preparation**:
```bash
ansible-playbook 0_start.yaml
```

3. **Or run individual components**:
```bash
# Update system packages
ansible-playbook general_vps_prepare_update.yaml

# Install essential packages
ansible-playbook general_vps_prepare_install_packages.yaml

# Set up Docker
ansible-playbook general_vps_prepare_install_docker.yaml

# Apply security hardening
ansible-playbook general_vps_prepare_secure.yaml
```

### Step-by-Step Deployment

The role provides decomposed playbooks for easier debugging and selective deployment:

1. **`0_start_step1.yaml`** - Core system preparation
2. **`0_start_step2.yaml`** - Package installation and tools
3. **`0_start_step3.yaml`** - Configuration and optimization

### Individual Playbook Functions

| Playbook | Function |
|----------|----------|
| `general_vps_prepare_update.yaml` | System package updates |
| `general_vps_prepare_install_packages.yaml` | Essential APT packages |
| `general_vps_prepare_install_eget.yaml` | Eget binary installer tool |
| `general_vps_prepare_install_packages_binary.yaml` | Modern CLI tools via eget |
| `general_vps_prepare_install_docker.yaml` | Docker platform setup |
| `general_vps_prepare_secure.yaml` | OS hardening |
| `general_vps_prepare_fail2ban.yaml` | Intrusion prevention |
| `general_vps_prepare_add_users.yaml` | User management |
| `general_vps_prepare_disable_password_auth.yaml` | SSH security |
| `general_vps_prepare_install_bash_profile.yaml` | Shell enhancement |
| `general_vps_prepare_install_ohmyposh.yaml` | Prompt beautification |
| `general_vps_prepare_configure_locale.yaml` | System localization |

## 🎖️ Achievements and Goals

### Infrastructure Goals Achieved

1. **Autonomous Operation**: Each server operates independently without external dependencies
2. **Security First**: Multiple layers of security hardening from the ground up
3. **Developer Experience**: Modern, user-friendly CLI environment
4. **Container Platform**: Full Docker ecosystem ready for application deployment
5. **Monitoring Ready**: Metrics and observability endpoints configured
6. **Scalable Foundation**: Consistent, reproducible server configuration

### Operational Benefits

- **Reduced Setup Time**: Automated server preparation in minutes
- **Consistent Environment**: Identical configuration across all servers
- **Enhanced Security**: Industry-standard security practices implemented
- **Improved Productivity**: Modern tools and enhanced user experience
- **Future-Proof**: Ready for additional specialized roles and services
- **Maintainable**: Ansible-driven configuration management

### Technical Achievements

- **33 Specialized Playbooks**: Modular, focused automation tasks
- **70+ Modern CLI Tools**: Comprehensive toolkit for system administration
- **Security Hardening**: DevSec compliance and best practices
- **Docker Integration**: Full container platform with optimization
- **Monitoring Integration**: Prometheus-ready metrics collection
- **Cross-Platform Support**: PowerShell and modern tools compatibility

## 🔗 Integration with Other Roles

The General VPS Prepare group serves as the foundation for other ansible-my roles:

- **Analytics Node**: Requires the monitoring-ready foundation
- **VPN Services**: Builds on the secure Docker platform
- **Backup Solutions**: Uses the installed backup tools (autorestic, rclone)
- **Web Services**: Leverages the Docker platform and security foundation

## 🚀 Getting Started

To begin using the General VPS Prepare group:

1. **Set up your inventory** with servers in the `general_vps_prepare` group
2. **Configure variables** in `group_vars/general_vps_prepare/`
3. **Run the preparation playbooks** using `0_start.yaml` or step-by-step
4. **Verify the setup** by connecting to your server and testing installed tools
5. **Proceed with specialized roles** like VPN, monitoring, or backup services

The General VPS Prepare group transforms your VPS from a basic server into a powerful, secure, and fully-equipped infrastructure platform ready for any workload.

---

*This documentation covers the comprehensive server preparation automation provided by the General VPS Prepare group in the ansible-my infrastructure automation suite.*