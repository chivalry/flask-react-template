#!/bin/bash
# PostToolUse hook: assigns newly created GitHub issues to chivalry.
input=$(cat)
command=$(printf '%s' "$input" | jq -r '.tool_input.command // ""')
printf '%s' "$command" | grep -q 'gh issue create' || exit 0

response=$(printf '%s' "$input" | jq -r '.tool_response.content // ""')
issue_url=$(printf '%s' "$response" \
  | grep -oE 'https://github\.com/[^/]+/[^/]+/issues/[0-9]+' \
  | head -1)
[ -n "$issue_url" ] || exit 0

repo=$(printf '%s' "$issue_url" \
  | sed 's|https://github.com/||' \
  | sed 's|/issues/.*||')
issue_num=$(printf '%s' "$issue_url" | grep -oE '[0-9]+$')
gh issue edit "$issue_num" --repo "$repo" --add-assignee chivalry
