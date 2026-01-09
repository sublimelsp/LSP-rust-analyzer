#!/usr/bin/env python3

from pathlib import Path
from typing import Any
from urllib.request import urlopen
import argparse
import difflib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile

Json = dict[str, Any]

REPOSITORY_URL = 'https://github.com/rust-lang/rust-analyzer'
CONFIGURATION_FILE_PATH = '/editors/code/package.json'


def download_github_artifact_by_tag(repository_url: str, tag: str, target_dir: str) -> Path:
    archive_url = f'{repository_url}/archive/{tag}.zip'
    zip_path = Path(target_dir, f'archive-{tag}.zip')

    with urlopen(archive_url) as response, Path.open(zip_path, 'wb') as out_file:  # noqa: S310
        shutil.copyfileobj(response, out_file)

    return zip_path


def extract_configuration_file(zip_path: Path, configuration_path: str, target_dir: str) -> Path:
    with zipfile.ZipFile(zip_path, 'r') as zip_file:
        filepath = next((p for p in zip_file.namelist() if configuration_path in p), None)
        if not filepath:
            print(f'Archive does not contain expected file {configuration_path}')
            sys.exit(1)
        return Path(zip_file.extract(filepath, target_dir))


def compare_json(contents_1: str, contents_2: str) -> tuple[Json, Json, list[str]]:
    # Filters out null values and flattens the result.
    jq_query = '[.contributes.configuration[].properties | select(. != null)] | add'
    flatten_settings_1: Json = json.loads(subprocess.check_output(  # noqa: S603
        ['jq', jq_query],  # noqa: S607
        input=contents_1,
        text=True,
        encoding='utf-8'))
    flatten_settings_2: Json = json.loads(subprocess.check_output(  # noqa: S603
        ['jq', jq_query],  # noqa: S607
        input=contents_2,
        text=True,
        encoding='utf-8'))

    # Find added, removed and changed keys.
    added: Json = {}
    changed: Json = {}
    removed: list[str] = [key for key in flatten_settings_1 if key not in flatten_settings_2]
    for key, value in flatten_settings_2.items():
        if key not in flatten_settings_1:
            added[key] = value
            continue

        if value != flatten_settings_1[key]:
            changed[key] = value

    return (added, changed, removed)


def json_format(contents: Any) -> str:
    return json.dumps(contents, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description='Checks for differences in configuration between two tags')
    _ = parser.add_argument('tag_from', help='First tag to compare.')
    _ = parser.add_argument('tag_to', help='Second tag to compare.')
    args = parser.parse_args()

    tag_from: str = args.tag_from
    tag_to: str = args.tag_to

    with tempfile.TemporaryDirectory() as tempdir:
        archive_path_1 = download_github_artifact_by_tag(REPOSITORY_URL, tag_from, tempdir)
        configuration_path_1 = extract_configuration_file(archive_path_1, CONFIGURATION_FILE_PATH, tempdir)
        archive_path_2 = download_github_artifact_by_tag(REPOSITORY_URL, tag_to, tempdir)
        configuration_path_2 = extract_configuration_file(archive_path_2, CONFIGURATION_FILE_PATH, tempdir)

        with Path.open(configuration_path_1, encoding='utf-8') as f1, \
                Path.open(configuration_path_2, encoding='utf-8') as f2:
            configuration_1 = f1.read()
            configuration_2 = f2.read()

        diff = '\n'.join(difflib.unified_diff(
            configuration_1.split('\n'),
            configuration_2.split('\n'),
            fromfile=tag_from,
            tofile=tag_to,
            lineterm=''))

        output: list[str] = [
            f'Following are the [settings schema]({REPOSITORY_URL}/blob/{tag_to}{CONFIGURATION_FILE_PATH}) changes between tags `{tag_from}` and `{tag_to}`. Make sure that those are reflected in the package settings and the `sublime-package.json` file.\n'
        ]

        if diff:
            added, changed, removed = compare_json(configuration_1, configuration_2)

            if added:
                output.append(f'Added keys:\n\n```json\n{json_format(added)}\n```')

                sublime_settings: list[str] = []
                for key, value in added.items():
                    description: str = value['markdownDescription'] if 'markdownDescription' in value else value['description']
                    wrapped_description: str = '\n'.join([f'// {line}'.rstrip() for line in description.splitlines()])
                    sublime_settings.append(f'{wrapped_description}\n"{key}": {json_format(value['default'])},')
                sublime_settings_str = '\n\n'.join(sublime_settings)
                output.append(f'New entries for package settings:\n\n```\n{sublime_settings_str}\n```')

            if changed:
                output.append(f'Changed keys:\n\n```json\n{json_format(changed)}\n```')

            if removed:
                items = [f' - `{k}`' for k in removed]
                output.append(f'Removed keys:\n{'\n'.join(items)}')

            output.append(f'All changes in `{CONFIGURATION_FILE_PATH}`:\n\n```diff\n{diff}\n```')
        else:
            output.append('No changes')

        print('\n\n'.join(output))

main()
