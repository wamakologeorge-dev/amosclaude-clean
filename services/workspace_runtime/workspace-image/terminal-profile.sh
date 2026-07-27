#!/usr/bin/env bash

# Interactive-only configuration for the Amosclaud developer terminal.
case "$-" in
  *i*) ;;
  *) return ;;
esac

export TERM="${TERM:-xterm-256color}"
export COLORTERM="${COLORTERM:-truecolor}"
export HISTFILE="/tmp/.amosclaud_bash_history"
export HISTCONTROL="ignoreboth:erasedups"
export HISTSIZE=5000
export HISTFILESIZE=10000
export EDITOR="${EDITOR:-nano}"
export VISUAL="${VISUAL:-nano}"

shopt -s checkwinsize cmdhist histappend 2>/dev/null || true

__amosclaud_prompt() {
  local previous_status=$?
  local branch=""
  local status_marker='\$'

  if command -v git >/dev/null 2>&1; then
    branch="$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
    if [[ -z "$branch" ]]; then
      branch="$(git rev-parse --short HEAD 2>/dev/null || true)"
    fi
  fi
  if [[ "$previous_status" -ne 0 ]]; then
    status_marker="!${previous_status}"
  fi

  PS1="\[\e]0;Amosclaud ${PWD##*/}${branch:+ [$branch]}\a\]"\
"\[\e[1;36m\]amosclaud\[\e[0m\]:"\
"\[\e[1;34m\]\w\[\e[0m\]"\
"${branch:+ \[\e[1;35m\]($branch)\[\e[0m\]} "\
"${status_marker} "
  return "$previous_status"
}

PROMPT_COMMAND='history -a; __amosclaud_prompt'
alias ll='ls -alF'
alias gs='git status --short --branch'
alias edit='amos edit'
alias files='amos files'
alias changed='amos changed'

if [[ -z "${AMOSCLAUD_TERMINAL_WELCOME_SHOWN:-}" ]]; then
  export AMOSCLAUD_TERMINAL_WELCOME_SHOWN=1
  printf '\n\033[1;36mAmosclaud workspace ready.\033[0m Edit with \033[1mamos edit <file>\033[0m or run \033[1mamos help\033[0m.\n\n'
fi
