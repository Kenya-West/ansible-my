Import-Module PSReadLine
Import-Module PSScriptTools
Import-Module posh-git
Import-Module PSFzf
set FZF_DEFAULT_OPTS='--no-height --no-reverse'
set FZF_ALT_C_OPTS="--preview 'tree -C {} | head -200'"
set FZF_CTRL_R_OPTS="--preview 'echo {}' --preview-window down:3:hidden:wrap --bind '?:toggle-preview'"
set FZF_CTRL_T_OPTS="--preview '(highlight -O ansi -l {} 2> /dev/null || cat {} || tree -C {}) 2> /dev/null | head -200'"
Set-PsFzfOption -PSReadlineChordProvider 'Ctrl+t' -PSReadlineChordReverseHistory 'Ctrl+r'
