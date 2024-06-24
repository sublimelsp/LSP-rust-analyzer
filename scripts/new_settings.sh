#!/usr/bin/env bash

# The following script prints differences in `rust-analyzer` settings
# between two tags.

# exit when any command fails
set -e

RA_REPO_URL="https://github.com/rust-lang/rust-analyzer"
RA_REPO_DIR=$(echo "${RA_REPO_URL}" | command grep -oE '[^/]*$')

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LSP_REPO_DIR="$SCRIPT_DIR/.."

if [ "$#" -ne 2 ]; then
   echo 'You must provide 2 arguments - two tags between which to check for diffrences in settings.'
   exit 1
fi

function download_rust_by_tag {
   tag=$1

   if [ ! "$tag" ]; then
      exit "No tag provided"
   fi

   pushd "${LSP_REPO_DIR}" > /dev/null || exit

   archive_url="${RA_REPO_URL}/archive/${tag}.zip"
   temp_zip="src-${tag}.zip"
   curl -L "${RA_REPO_URL}/archive/${tag}.zip" -o "${temp_zip}" --silent --show-error
   unzip -q "${temp_zip}"
   rm -f "${temp_zip}" || exit
   mv "${RA_REPO_DIR}-"* "${RA_REPO_DIR}"
}

tag_from=$1
tag_to=$2

download_rust_by_tag "$tag_from"
settings_from=$(jq ".contributes.configuration.properties" "${RA_REPO_DIR}/editors/code/package.json")
rm -rf "${RA_REPO_DIR}"

download_rust_by_tag "$tag_to"
settings_to=$(jq ".contributes.configuration.properties" "${RA_REPO_DIR}/editors/code/package.json")
rm -rf "${RA_REPO_DIR}"

# Returns with error code when there are changes.
changes=$(diff -u <(echo "$settings_from") <(echo "$settings_to") || echo "")
if [ "$changes" = "" ]; then
   echo "No changes"
else
   echo "$changes"
fi
