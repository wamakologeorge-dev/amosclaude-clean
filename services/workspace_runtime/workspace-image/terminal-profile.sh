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
