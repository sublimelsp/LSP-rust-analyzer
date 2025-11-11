from LSP.plugin import AbstractPlugin
from LSP.plugin import register_plugin
from LSP.plugin import Request
from LSP.plugin import Session
from LSP.plugin import unregister_plugin
from LSP.plugin.core.protocol import Location
from LSP.plugin.core.protocol import Position
from LSP.plugin.core.registry import LspTextCommand
from LSP.plugin.core.typing import Optional, Union, List, Any, TypedDict, Mapping, Callable, Dict
from LSP.plugin.core.views import first_selection_region
from LSP.plugin.core.views import Point
from LSP.plugin.core.views import point_to_offset
from LSP.plugin.core.views import region_to_range
from LSP.plugin.core.views import text_document_position_params
from LSP.plugin.locationpicker import LocationPicker
import gzip
import os
import shutil
import sublime
import urllib.request
import functools
import zipfile


try:
    import Terminus  # type: ignore
except ImportError:
    Terminus = None


SESSION_NAME = "rust-analyzer"

TAG = "2025-11-10"
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

RunnableArgs = TypedDict('RunnableArgs', {
    'cargoArgs': List[str],
    'executableArgs': List[str],
    'overrideCargo': Optional[str],
    'workspaceRoot': str,
}, total=True)

Runnable = TypedDict('Runnable', {
    'args': RunnableArgs,
    'kind': str,
    'label': str,
}, total=True)


def arch() -> str:
    if sublime.arch() == "x64":
        return "x86_64"
    elif sublime.arch() == "x32":
        raise RuntimeError("Unsupported platform: 32-bit is not supported")
    elif sublime.arch() == "arm64":
        return "aarch64"
    else:
        raise RuntimeError("Unknown architecture: " + sublime.arch())


def get_setting(view: sublime.View, key: str, default: Optional[Union[str, bool]] = None) -> Any:
    settings = view.settings()
    if settings.has(key):
        return settings.get(key)
    settings = sublime.load_settings('LSP-rust-analyzer.sublime-settings').get("settings", {})
    return settings.get(key, default)


def platform() -> str:
    if sublime.platform() == "windows":
        return "pc-windows-msvc"
    elif sublime.platform() == "osx":
        return "apple-darwin"
    else:
        return "unknown-linux-gnu"


def open_runnables_in_terminus(window: Optional[sublime.Window], runnables: List[Runnable]) -> None:
    filtered_runnables = [r for r in runnables if r["kind"] == "cargo"]
    if len(filtered_runnables) == 0:
        return
    if not window:
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
        command_to_run = [cargo_path] + args.get("cargoArgs", [])
        
        if not shutil.which(command_to_run[0]):
            sublime.error_message(
                'Cannot run executable "{}". Ensure that it is in the PATH of the Sublime Text process.'.format(command_to_run[0]))
            return
        if args.get("executableArgs"):
            command_to_run += ['--'] + args["executableArgs"]
        terminus_args = {
            "title": runnable["label"],
            "cmd": command_to_run,
            "cwd": args["workspaceRoot"],
            "auto_close": get_setting(view, "rust-analyzer.terminusAutoClose", False)
        }
        if get_setting(view, "rust-analyzer.terminusUsePanel", False):
            terminus_args["panel_name"] = runnable["label"]
        window.run_command("terminus_open", terminus_args)


class RustAnalyzer(AbstractPlugin):

    @classmethod
    def name(cls) -> str:
        return SESSION_NAME

    @classmethod
    def basedir(cls) -> str:
        return os.path.join(cls.storage_path(), __package__)

    @classmethod
    def server_version(cls) -> str:
        return TAG

    @classmethod
    def current_server_version(cls) -> str:
        with open(os.path.join(cls.basedir(), "VERSION"), "r") as fp:
            return fp.read()

    @classmethod
    def needs_update_or_installation(cls) -> bool:
        try:
            return cls.server_version() != cls.current_server_version()
        except OSError:
            return True

    @classmethod
    def install_or_update(cls) -> None:
        try:
            if os.path.isdir(cls.basedir()):
                shutil.rmtree(cls.basedir())
            os.makedirs(cls.basedir(), exist_ok=True)
            version = cls.server_version()
            is_windows = sublime.platform() == "windows"
            extension = "zip" if is_windows else "gz"
            url = URL.format(tag=TAG, arch=arch(), platform=platform(), ext=extension)
            archive_file = os.path.join(cls.basedir(), f"rust-analyzer.{extension}")
            rust_analyzer_filename = "rust-analyzer.exe" if is_windows else "rust-analyzer"
            rust_analyzer_path = os.path.join(cls.basedir(), rust_analyzer_filename)
            with urllib.request.urlopen(url) as fp:
                with open(archive_file, "wb") as f:
                    f.write(fp.read())

            if is_windows:
                with zipfile.ZipFile(archive_file, "r") as zip_ref:
                    zip_ref.extract(rust_analyzer_filename, cls.basedir())
            else:
                with gzip.open(archive_file, "rb") as fp:
                    with open(rust_analyzer_path, "wb") as f:
                        f.write(fp.read())
            os.remove(archive_file)
            os.chmod(rust_analyzer_path, 0o744)
            with open(os.path.join(cls.basedir(), "VERSION"), "w") as fp:
                fp.write(version)
        except BaseException:
            shutil.rmtree(cls.basedir(), ignore_errors=True)
            raise

    def on_pre_send_request_async(self, request_id: int, request: Request) -> None:
        if request.method == 'textDocument/hover' and request.view:
            session = self.weaksession()
            if not session:
                return
            if not session.get_capability('experimental.hoverRange'):
                return
            view = request.view
            region = first_selection_region(view)
            if region is not None:
                position = request.params['position']  # type: Position
                point = point_to_offset(Point.from_lsp(position), view)
                if region.contains(point):
                    request.params['position'] = region_to_range(view, region)

    def on_pre_server_command(self, command: Mapping[str, Any], done_callback: Callable[[], None]) -> bool:
        command_name = command["command"]
        try:
            session = self.weaksession()
            if not session:
                return False
            if command_name in ("rust-analyzer.runSingle", "rust-analyzer.runDebug"):
                open_runnables_in_terminus(sublime.active_window(), command["arguments"])
                done_callback()
                return True
            elif command_name == "rust-analyzer.showReferences":
                return self._handle_show_references(session, command, done_callback)
            elif command_name == "rust-analyzer.triggerParameterHints":
                done_callback()
                return True
            else:
                return False
        except Exception as ex:
            print("Exception handling command {}: {}".format(command_name, ex))
            return False

    def _handle_show_references(
        self,
        session: Session,
        command: Mapping[str, Any],
        done_callback: Callable[[], None]
    ) -> bool:
        locations = command["arguments"][2]
        view = session.window.active_view()
        if not view:
            return True
        LocationPicker(view, session, locations, side_by_side=False)
        done_callback()
        return True

    def is_valid_for_view(self, view: sublime.View) -> bool:
        session = self.weaksession()
        return bool(session and session.session_view_for_view_async(view))


class RustAnalyzerCommand(LspTextCommand):
    session_name = SESSION_NAME


class RustAnalyzerOpenDocsCommand(RustAnalyzerCommand):

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

    def on_result_async(self, url: Optional[str]) -> None:
        window = self.view.window()
        if window is None:
            return
        if url is not None:
            window.run_command("open_url", {"url": url})


class RustAnalyzerMemoryUsage(RustAnalyzerCommand):

    def run(self, edit: sublime.Edit) -> None:
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        session.send_request(
            Request("rust-analyzer/memoryUsage"),
            lambda response: sublime.set_timeout(functools.partial(self.on_result, response))
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


class RustAnalyzerExec(RustAnalyzerCommand):

    def run(self, edit: sublime.Edit) -> None:
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        params = text_document_position_params(self.view, self.view.sel()[0].b)
        session.send_request(Request("experimental/runnables", params), self.on_result)

    def run_terminus(self, check_phrase: str, runnables: List[Runnable]) -> None:
        for runnable in runnables:
            if runnable["label"].startswith(check_phrase):
                open_runnables_in_terminus(self.view.window(), [runnable])

    def on_result(self, payload: Any) -> None:
        raise NotImplementedError()


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

    def on_result_async(self, payload: List[Runnable]) -> None:
        items = [item["label"] for item in payload]
        self.items = items
        self.payload = payload
        view = self.view
        window = view.window()
        if window is None:
            return
        window.show_quick_panel(items, self.callback)

    def callback(self, option: int) -> None:
        if option == -1:
            return
        self.run_terminus(self.items[option], self.payload)


class RustAnalyzerOpenCargoToml(RustAnalyzerCommand):

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


class RustAnalyzerSyntaxTree(RustAnalyzerCommand):

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
        session.send_request(
            Request("rust-analyzer/syntaxTree", params),
            lambda response: sublime.set_timeout(functools.partial(self.on_result, response))
        )

    def on_result(self, out: Optional[str]) -> None:
        window = self.view.window()
        if window is None:
            return
        if out is None:
            return
        sheets = window.selected_sheets()
        view = window.new_file(flags=sublime.TRANSIENT)
        view.set_scratch(True)
        view.set_name("Syntax Tree")
        # Resource Aware Session Types Syntax highlighting not available
        view.run_command("append", {"characters": out})
        view.set_read_only(True)
        sheet = view.sheet()
        if sheet is not None:
            sheets.append(sheet)
            window.select_sheets(sheets)


class RustAnalyzerViewItemTree(RustAnalyzerCommand):

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
            lambda response: sublime.set_timeout(functools.partial(self.on_result, response))
        )

    def on_result(self, out: Optional[str]) -> None:
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


class RustAnalyzerReloadProject(RustAnalyzerCommand):

    def run(self, _: sublime.Edit) -> None:
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        session.send_request(Request("rust-analyzer/reloadWorkspace"), lambda _: None)


class RustAnalyzerExpandMacro(RustAnalyzerCommand):

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
            lambda response: sublime.set_timeout(functools.partial(self.on_result, response))
        )

    def on_result(self, expanded_macro: Optional[Dict[str, str]]) -> None:
        if expanded_macro is None:
            return
        window = self.view.window()
        if window is None:
            return
        header = "Recursive expansion of {0}! macro".format(expanded_macro["name"])
        content = "// {0}\n// {1}\n\n{2}".format(header, (1 + len(header)) * "=", expanded_macro["expansion"])
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
    register_plugin(RustAnalyzer)


def plugin_unloaded() -> None:
    unregister_plugin(RustAnalyzer)
