#!/bin/sh
# Starts BaggageFlow and opens it in the browser. On macOS double-click this
# file; on Linux run ./BaggageFlow.command in a terminal. Press Ctrl+C (or
# close the window) to stop it.
cd "$(dirname "$0")" || exit 1
if ! command -v uv >/dev/null 2>&1; then
  echo "BaggageFlow needs uv: https://docs.astral.sh/uv/getting-started/installation/"
  printf "Press Enter to close. "
  read -r _
  exit 1
fi
uv run --locked baggageflow "$@"
status=$?
if [ "$status" -ne 0 ]; then
  printf "Press Enter to close. "
  read -r _
fi
exit "$status"
