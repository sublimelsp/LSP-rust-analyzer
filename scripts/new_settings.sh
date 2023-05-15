#!/usr/bin/env bash

# The following script finds the keys that are in the `rust-analyzer`
# package.json, but not in `LSP-rust-analyzer`'s sublime-settings.

# exit when any command fails
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LSP_REPO_DIR="$SCRIPT_DIR/.."
RA_REPO_DIR=/usr/local/workspace/github/rust-analyzer/

lsp_ra_settings=$(rg -o '"rust-analyzer.([^"]+)"' "${LSP_REPO_DIR}/LSP-rust-analyzer.sublime-settings" | sort)
ra_settings=$(jq '.contributes.configuration.properties
        | to_entries
        | map(.key)
        | .[] | select(. != "$generated-start" and . != "$generated-end")' \
        "${RA_REPO_DIR}/editors/code/package.json" | sort)

# Missing settings in LSP-rust-analyzer
rg -vf <(echo "${lsp_ra_settings}") <(echo "${ra_settings}")

# Settings in LSP-rust-analyzer that are no longer relevant
rg -vf <(echo "${ra_settings}") <(echo "${lsp_ra_settings}") \
   | rg -v 'terminusAutoClose|terminusUsePanel'
