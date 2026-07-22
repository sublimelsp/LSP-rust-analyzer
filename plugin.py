from __future__ import annotations

from functools import partial
from LSP.plugin import ClientConfig
from LSP.plugin import ClientRequest
from LSP.plugin import command_handler
from LSP.plugin import LspPlugin
from LSP.plugin import LspTextCommand
from LSP.plugin import OnPreStartContext
from LSP.plugin import Promise
from LSP.plugin import Request
from LSP.plugin import ServerResponse
from LSP.plugin.core.protocol import Point
from LSP.plugin.core.views import first_selection_region
from LSP.plugin.core.views import point_to_offset
from LSP.plugin.core.views import region_to_range
from LSP.plugin.core.views import text_document_position_params
from LSP.protocol import AnnotatedTextEdit
from LSP.protocol import InsertTextFormat
from LSP.protocol import LSPAny
from LSP.protocol import SnippetTextEdit
from LSP.protocol import TextEdit
from typing import Any
from typing import cast
from typing import TYPE_CHECKING
from typing import TypedDict
from typing_extensions import override
import gzip
import shutil
import sublime
import urllib.request
import zipfile

if TYPE_CHECKING:
    from LSP.protocol import Location


try:
    import Terminus  # type: ignore
except ImportError:
    Terminus = None


TAG = "2026-07-20"
"""
Update this single git tag to download a newer version.
After changing this tag, go through the server settings again to see
if any new server settings are added or old ones removed.
Compare the previous and new tags's editors/code/package.json with
https://github.com/rust-lang/rust-analyzer/compare/2023-01-30...2023-05-15

The script in `./scripts/new_settings.sh can be used to find the keys that are in the `rust-analyzer`
package.json, but not in `LSP-rust-analyzer`'s sublime-settings.
"""

URL = "https://github.com/rust-analyzer/rust-analyzer/releases/download/{tag}/rust-analyzer-{arch}-{platform}.{ext}"


class RunnableArgs(TypedDict, total=True):
    cargoArgs: list[str]
    executableArgs: list[str]
    overrideCargo: str | None
    workspaceRoot: str


class Runnable(TypedDict, total=True):
    args: RunnableArgs
    kind: str
    label: str


def arch() -> str:
    arch = sublime.arch()
    if arch == "x64":
        return "x86_64"
    if arch == "x32":
        raise RuntimeError("Unsupported platform: 32-bit is not supported")
    if arch == "arm64":
        return "aarch64"
    raise RuntimeError("Unknown architecture: " + arch)


def platform() -> str:
    platform = sublime.platform()
    if platform == "windows":
        return "pc-windows-msvc"
    if platform == "osx":
        return "apple-darwin"
    return "unknown-linux-gnu"


def open_runnables_in_terminus(window: sublime.Window, runnables: list[Runnable], config: ClientConfig) -> None:
    filtered_runnables = [r for r in runnables if r["kind"] == "cargo"]
    if len(filtered_runnables) == 0:
        return
    view = window.active_view()
    if not view:
        return
    if not Terminus:
        sublime.error_message(
            'Cannot run executable. You need to install the "Terminus" package and then restart Sublime Text')
        return
    for runnable in filtered_runnables:
        args = runnable["args"]
        cargo_path = args.get("overrideCargo") or 'cargo'
        command_to_run = [cargo_path, *args.get("cargoArgs", [])]
        if not shutil.which(command_to_run[0]):
            sublime.error_message(
                f'Cannot run executable "{command_to_run[0]}". Ensure that it is in the PATH of the Sublime Text process.')
            return
        if args.get("executableArgs"):
            command_to_run += ['--'] + args["executableArgs"]
        terminus_args = {
            "title": runnable["label"],
            "cmd": command_to_run,
            "cwd": args["workspaceRoot"],
            "auto_close": get_package_setting(config, "terminusAutoClose", default=False)
        }
        if get_package_setting(config, "terminusUsePanel", default=False):
            terminus_args["panel_name"] = runnable["label"]
        window.run_command("terminus_open", terminus_args)


def get_package_setting(config: ClientConfig, key: str, *, default: Any = None) -> Any:
    legacy_key = f'rust-analyzer.{key}'
    if legacy_key in config.settings:
        return config.settings.get(legacy_key, default)
    return config.initialization_options.get(key, default)

class RustAnalyzer(LspPlugin):

    @classmethod
    @override
    def on_pre_start_async(cls, context: OnPreStartContext) -> None:
        server_path = context.configuration.root_settings.get('server_path')
        if not server_path or server_path == 'auto':
            cls.install_server()
            server_path = str(cls.plugin_storage_path / 'rust-analyzer')
        context.variables.update({'server_path': server_path})
        # Copy initialization_options to settings.
        legacy_settings = context.configuration.settings.get('rust-analyzer') or {}
        context.configuration.initialization_options.update(legacy_settings)
        context.configuration.settings.set('rust-analyzer', context.configuration.initialization_options.get())

    @classmethod
    def install_server(cls) -> None:
        version_file_path = cls.plugin_storage_path / "VERSION"
        if version_file_path.is_file() and version_file_path.read_text(encoding="utf-8") == TAG:
            return
        try:
            if cls.plugin_storage_path.is_dir():
                shutil.rmtree(cls.plugin_storage_path)
            cls.plugin_storage_path.mkdir(exist_ok=True, parents=True)
            is_windows = sublime.platform() == "windows"
            extension = "zip" if is_windows else "gz"
            url = URL.format(tag=TAG, arch=arch(), platform=platform(), ext=extension)
            archive_file = cls.plugin_storage_path / f"rust-analyzer.{extension}"
            rust_analyzer_filename = "rust-analyzer.exe" if is_windows else "rust-analyzer"
            rust_analyzer_path = cls.plugin_storage_path / rust_analyzer_filename
            with urllib.request.urlopen(url) as fp, open(archive_file, "wb") as f:
                f.write(fp.read())
            if is_windows:
                with zipfile.ZipFile(archive_file, "r") as zip_ref:
                    zip_ref.extract(rust_analyzer_filename, cls.plugin_storage_path)
            else:
                with gzip.open(archive_file, "rb") as fp, open(rust_analyzer_path, "wb") as f:
                    f.write(fp.read())
            archive_file.unlink()
            rust_analyzer_path.chmod(0o744)
            version_file_path.write_text(TAG, encoding='utf-8')
        except BaseException:
            shutil.rmtree(cls.plugin_storage_path, ignore_errors=True)
            raise

    @override
    def on_pre_send_request_async(self, request: ClientRequest, view: sublime.View | None) -> None:
        if (
            request['method'] == 'textDocument/hover' and view
            and (session := self.weaksession())
            and session.get_capability('experimental.hoverRange')
        ):
            if (region := first_selection_region(view)) is not None:
                params = request['params']
                point = point_to_offset(Point.from_lsp(params['position']), view)
                if region.contains(point):
                    params['position'] = region_to_range(view, region)  # pyright: ignore[reportGeneralTypeIssues]
            return

    @override
    def on_server_response_async(self, response: ServerResponse) -> None:
        if response['method'] == 'codeAction/resolve':
            result = response['result']
            if (edit := result.get('edit')) and (document_changes := edit.get('documentChanges')):
                for change in document_changes:
                    if 'edits' in change:
                        for edit in change['edits']:
                            if 'newText' in edit:
                                self.convert_proprietary_snippet(edit)
            return

    def convert_proprietary_snippet(self, edit: TextEdit | AnnotatedTextEdit) -> None:
        if edit.get('insertTextFormat') == InsertTextFormat.Snippet:
            cast('SnippetTextEdit', edit)['snippet'] = {'kind': 'snippet', 'value': edit['newText']}


    @command_handler('rust-analyzer.runSingle')
    @command_handler('rust-analyzer.runDebug')
    def handle_run_single_command(self, arguments: list[Runnable] | None) -> Promise[None]:
        if session := self.weaksession():
            open_runnables_in_terminus(session.window, arguments or [], session.config)
        return Promise.resolve(None)

    @command_handler('rust-analyzer.showReferences')
    def handle_show_references_command(self, arguments: list[LSPAny] | None) -> Promise[None]:
        if session := self.weaksession():
            session.execute_command({
                'command': 'editor.action.showReferences',
                'arguments': arguments or [],
            })
        return Promise.resolve(None)

    @command_handler('rust-analyzer.triggerParameterHints')
    def handle_trigger_parameter_hints_command(self, arguments: list[LSPAny] | None) -> Promise[None]:
        if session := self.weaksession():
            session.execute_command({
                'command': 'editor.action.triggerParameterHints',
                'arguments': arguments or [],
            })
        return Promise.resolve(None)


class RustAnalyzerOpenDocsCommand(LspTextCommand):

    def is_enabled(self) -> bool:
        selection = self.view.sel()
        if len(selection) == 0:
            return False
        return super().is_enabled()

    def run(self, edit: sublime.Edit) -> None:
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        params = text_document_position_params(self.view, self.view.sel()[0].b)
        session.send_request(Request("experimental/externalDocs", params), self.on_result_async)

    def on_result_async(self, url: str | None) -> None:
        window = self.view.window()
        if window is None:
            return
        if url is not None:
            window.run_command("open_url", {"url": url})


class RustAnalyzerMemoryUsage(LspTextCommand):

    def run(self, edit: sublime.Edit) -> None:
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        session.send_request(
            Request("rust-analyzer/memoryUsage"),
            lambda response: sublime.set_timeout(partial(self.on_result, response))
        )

    def on_result(self, payload: str) -> None:
        window = self.view.window()
        if window is None:
            return
        sheets = window.selected_sheets()
        view = window.new_file(flags=sublime.TRANSIENT)
        view.set_scratch(True)
        view.set_name("--- RustAnalyzer Memory Usage ---")
        view.run_command("append", {"characters": "Per-query memory usage:\n"})
        view.run_command("append", {"characters": payload})
        view.run_command("append", {"characters": "\n(note: database has been cleared)"})
        view.set_read_only(True)
        sheet = view.sheet()
        if sheet is not None:
            sheets.append(sheet)
            window.select_sheets(sheets)


class RustAnalyzerExec(LspTextCommand):

    def run(self, edit: sublime.Edit) -> None:
        if session := self.session_by_name(self.session_name):
            params = text_document_position_params(self.view, self.view.sel()[0].b)
            session.send_request(Request("experimental/runnables", params), self.on_result)

    def run_terminus(self, check_phrase: str, runnables: list[Runnable]) -> None:
        if session := self.session_by_name(self.session_name):
            for runnable in runnables:
                if runnable["label"].startswith(check_phrase):
                    open_runnables_in_terminus(session.window, [runnable], session.config)

    def on_result(self, payload: Any) -> None:
        raise NotImplementedError


class RustAnalyzerRunProject(RustAnalyzerExec):

    def is_enabled(self) -> bool:
        selection = self.view.sel()
        if len(selection) == 0:
            return False
        return super().is_enabled()

    def run(self, edit: sublime.Edit) -> None:
        params = text_document_position_params(self.view, self.view.sel()[0].b)
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        session.send_request(Request("experimental/runnables", params), self.on_result_async)

    def on_result_async(self, payload: list[Runnable]) -> None:
        items = [item["label"] for item in payload]
        view = self.view
        window = view.window()
        if window is None:
            return
        window.show_quick_panel(items, partial(self.callback, items, payload))

    def callback(self, items: list[str], payload: list[Runnable], option: int) -> None:
        if option == -1:
            return
        self.run_terminus(items[option], payload)


class RustAnalyzerOpenCargoToml(LspTextCommand):

    def is_enabled(self) -> bool:
        selection = self.view.sel()
        if len(selection) == 0:
            return False
        return super().is_enabled()

    def run(self, edit: sublime.Edit) -> None:
        params = text_document_position_params(self.view, self.view.sel()[0].b)
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        session.send_request(Request("experimental/openCargoToml", params), self.on_result_async)

    def on_result_async(self, payload: Location) -> None:
        window = self.view.window()
        if window is None:
            return
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        session.open_location_async(payload)


class RustAnalyzerViewItemTree(LspTextCommand):

    def is_enabled(self) -> bool:
        selection = self.view.sel()
        if len(selection) == 0:
            return False
        return super().is_enabled()

    def run(self, _: sublime.Edit) -> None:
        params = text_document_position_params(self.view, self.view.sel()[0].b)
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        session.send_request(
            Request("rust-analyzer/viewItemTree", params),
            lambda response: sublime.set_timeout(partial(self.on_result, response))
        )

    def on_result(self, out: str | None) -> None:
        window = self.view.window()
        if window is None:
            return
        if out is None:
            return
        sheets = window.selected_sheets()
        view = window.new_file(flags=sublime.TRANSIENT)
        view.set_scratch(True)
        view.set_name("View Item Tree")
        view.assign_syntax("scope:source.rust")
        view.run_command("append", {"characters": out})
        view.set_read_only(True)
        sheet = view.sheet()
        if sheet is not None:
            sheets.append(sheet)
            window.select_sheets(sheets)


class RustAnalyzerReloadProject(LspTextCommand):

    def run(self, _: sublime.Edit) -> None:
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        session.send_request(Request("rust-analyzer/reloadWorkspace"), lambda _: None)


class RustAnalyzerExpandMacro(LspTextCommand):

    def is_enabled(self) -> bool:
        selection = self.view.sel()
        if len(selection) == 0:
            return False
        return super().is_enabled()

    def run(self, _: sublime.Edit) -> None:
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        params = text_document_position_params(self.view, self.view.sel()[0].b)
        session.send_request(
            Request("rust-analyzer/expandMacro", params),
            lambda response: sublime.set_timeout(partial(self.on_result, response))
        )

    def on_result(self, expanded_macro: dict[str, str] | None) -> None:
        if expanded_macro is None:
            return
        window = self.view.window()
        if window is None:
            return
        header = f"Recursive expansion of {expanded_macro['name']}! macro"
        content = f"// {header}\n// {(1 + len(header)) * '='}\n\n{expanded_macro['expansion']}"
        sheets = window.selected_sheets()
        view = window.new_file(flags=sublime.TRANSIENT)
        view.set_scratch(True)
        view.set_name("Macro Expansion")
        view.assign_syntax("scope:source.rust")
        view.run_command("append", {"characters": content})
        view.set_read_only(True)
        sheet = view.sheet()
        if sheet is not None:
            sheets.append(sheet)
            window.select_sheets(sheets)


def plugin_loaded() -> None:
    RustAnalyzer.register()


def plugin_unloaded() -> None:
    RustAnalyzer.unregister()
