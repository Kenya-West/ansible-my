alias ls='eza --icons'
alias l='ls -l'
alias la='ls -a'
alias lt='ls --tree'

alias dps='docker ps --format \"{{.ID}}\\t{{.Status}}\\t{{.Names}}\"'
alias dc='docker compose'

alias fd=fdfind

alias lg=lazygit
alias ld=lazydocker
alias lj=lazyjournal

alias bat=batcat
alias cat='bat --paging=never'

alias norg='gron --ungron'
alias ungron='gron --ungron'

# Set up fzf key bindings and fuzzy completion
eval "$(fzf --bash)"
export FZF_DEFAULT_OPTS='--no-height --no-reverse'
export FZF_ALT_C_OPTS="--preview 'tree -C {} | head -200'"
export FZF_CTRL_R_OPTS="--preview 'echo {}' --preview-window down:3:hidden:wrap --bind '?:toggle-preview'"
# Using highlight (http://www.andre-simon.de/doku/highlight/en/highlight.html)
export FZF_CTRL_T_OPTS="--preview '(highlight -O ansi -l {} 2> /dev/null || cat {} || tree -C {}) 2> /dev/null | head -200'"

eval "$(zoxide init bash)"
