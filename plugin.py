from LSP.plugin import AbstractPlugin
from LSP.plugin import register_plugin
from LSP.plugin import Request
from LSP.plugin import unregister_plugin
from LSP.plugin.core.registry import LspTextCommand
from LSP.plugin.core.typing import Optional, Union, List, Any, TypedDict, Mapping, Callable
from LSP.plugin.core.views import text_document_position_params
import gzip
import os
import shutil
import sublime
import urllib.request


try:
    import Terminus  # type: ignore
except ImportError:
    Terminus = None

# Update this single git tag to download a newer version.
# After changing this tag, go through the server settings
# again to see if any new server settings are added or
# old ones removed.
TAG = "2021-06-07"

URL = "https://github.com/rust-analyzer/rust-analyzer/releases/download/{tag}/rust-analyzer-{arch}-{platform}.gz"  # noqa: E501


def arch() -> str:
    if sublime.arch() == "x64":
        return "x86_64"
    elif sublime.arch() == "x32":
        raise RuntimeError("Unsupported platform: 32-bit is not supported")
    elif sublime.arch() == "arm64":
        return "aarch64"
    else:
        raise RuntimeError("Unknown architecture: " + sublime.arch())


def get_setting(view: sublime.View, key: str, default: Optional[Union[str, bool]] = None) -> Union[bool, str]:
    settings = view.settings()
    if settings.has(key):
        return settings.get(key)
    settings = sublime.load_settings('LSP-rust-analyzer.sublime-settings')
    return settings.get(key, default)


def platform() -> str:
    if sublime.platform() == "windows":
        return "pc-windows-msvc"
    elif sublime.platform() == "osx":
        return "apple-darwin"
    else:
        return "unknown-linux-gnu"


class RustAnalyzer(AbstractPlugin):

    @classmethod
    def name(cls) -> str:
        return "rust-analyzer"

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
            url = URL.format(tag=TAG, arch=arch(), platform=platform())
            gzipfile = os.path.join(cls.basedir(), "rust-analyzer.gz")
            serverfile = os.path.join(
                cls.basedir(),
                "rust-analyzer.exe" if sublime.platform() == "windows" else "rust-analyzer"
            )
            with urllib.request.urlopen(url) as fp:
                with open(gzipfile, "wb") as f:
                    f.write(fp.read())
            with gzip.open(gzipfile, "rb") as fp:
                with open(serverfile, "wb") as f:
                    f.write(fp.read())
            os.remove(gzipfile)
            os.chmod(serverfile, 0o744)
            with open(os.path.join(cls.basedir(), "VERSION"), "w") as fp:
                fp.write(version)
        except Exception:
            shutil.rmtree(cls.basedir(), ignore_errors=True)
            raise

    def on_pre_server_command(self, command: Mapping[str, Any], done_callback: Callable[[], None]) -> bool:

        cargo_commands = []
        for c in command["arguments"]:
            if c["kind"] == "cargo":
                cargo_commands.append(c)

        if len(cargo_commands) == 0:
            return False

        window = sublime.active_window()
        if window is None:
            return False
        view = window.active_view()
        if not view:
            return False
        if not Terminus:
            sublime.error_message(
                'Cannot run executable "{}": You need to install the "Terminus" package and then restart Sublime Text'.format(output["kind"]))
            return False

        for output in cargo_commands:
            if output["args"]["overrideCargo"]:
                cargo_path = output["args"]["overrideCargo"]
            else:
                if not shutil.which("cargo"):
                    sublime.error_message('Cannot find "cargo" on path.')
                    return False
                cargo_path = '"{}"'.format(shutil.which("cargo"))
            command_to_run = [cargo_path] + output["args"]["cargoArgs"] + \
                output["args"]["cargoExtraArgs"]
            cmd = " ".join(command_to_run)
            args = {
                "title": output["label"],
                "shell_cmd": cmd,
                "cwd": output["args"]["workspaceRoot"],
                "auto_close": get_setting(view, "terminus_auto_close", False)
            }
            if get_setting(view, "terminus_use_panel", False):
                args["panel_name"] = output["label"]
            window.run_command("terminus_open", args)
        return True


class RustAnalyzerOpenDocsCommand(LspTextCommand):
    session_name = "rust-analyzer"

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

        session.send_request(Request("experimental/externalDocs", params), self.on_result)

    def on_result(self, url: Optional[str]) -> None:
        window = self.view.window()
        if window is None:
            return

        if url is not None:
            window.run_command("open_url", {"url": url})


class RustAnalyzerReloadProject(LspTextCommand):
    session_name = "rust-analyzer"

    def run(self, edit: sublime.Edit) -> None:
        session = self.session_by_name(self.session_name)
        if session is None:
            return

        session.send_request(Request("rust-analyzer/reloadWorkspace"), self.on_result)

    def on_result(self, arg: Any):
        pass


class RustAnalyzerMemoryUsage(LspTextCommand):
    session_name = "rust-analyzer"

    def run(self, edit: sublime.Edit) -> None:
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        session.send_request(Request("rust-analyzer/memoryUsage"), self.on_result)

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


RunnableArgs = TypedDict('RunnableArgs', {
    'cargoArgs': List[str],
    'cargoExtraArgs': List[str],
    'executableArgs': List[str],
    'overrideCargo': Optional[str],
    'workspaceRoot': str,
})
Runnable = TypedDict('Runnable', {
    'args': RunnableArgs,
    'kind': str,
    'label': str,
})


class RustAnalyzerExec(LspTextCommand):
    session_name = "rust-analyzer"

    def run(self, edit: sublime.Edit) -> None:
        params = text_document_position_params(self.view, self.view.sel()[0].b)
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        session.send_request(Request("experimental/runnables", params), self.on_result)

    def run_termius(self, check_phrase: str, payload: List[Runnable]) -> None:
        window = self.view.window()
        if window is None:
            return

        if len(payload) == 0:
            return

        output = None
        for item in payload:
            if item["label"].startswith(check_phrase):
                output = item
                break

        if not output:
            return

        if not Terminus:
            sublime.error_message(
                'Cannot run executable "{}": You need to install the "Terminus" package and then restart Sublime Text'.format(output["kind"]))
            return
        if output["args"]["overrideCargo"]:
            cargo_path = output["args"]["overrideCargo"]
        else:
            if not shutil.which("cargo"):
                sublime.error_message('Cannot find "cargo" on path.')
                return
            cargo_path = '"{}"'.format(shutil.which("cargo"))
        command_to_run = [cargo_path] + output["args"]["cargoArgs"] + \
            output["args"]["cargoExtraArgs"] + output["args"]["executableArgs"]
        print(command_to_run)
        cmd = " ".join(command_to_run)
        args = {
            "title": output["label"],
            "shell_cmd": cmd,
            "cwd": output["args"]["workspaceRoot"],
            "auto_close": get_setting(self.view, "terminus_auto_close", False)
        }
        if get_setting(self.view, "terminus_use_panel", False):
            args["panel_name"] = output["label"]
        window.run_command("terminus_open", args)

    def on_result(self, payload: Any) -> None:
        raise NotImplementedError()


class RustAnalyzerRunProject(RustAnalyzerExec):
    session_name = "rust-analyzer"

    def run(self, edit: sublime.Edit) -> None:
        params = text_document_position_params(self.view, self.view.sel()[0].b)
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        session.send_request(Request("experimental/runnables", params), self.on_result)

    def on_result(self, payload: List[Runnable]) -> None:
        items = [item["label"] for item in payload]
        self.items = items
        self.payload = payload
        view = self.view
        window = view.window()
        if window is None:
            return
        sublime.set_timeout(
            lambda: window.show_quick_panel(items, self.callback)
        )

    def callback(self, option: int) -> None:
        if option == -1:
            return
        self.run_termius(self.items[option], self.payload)


class RustAnalyzerCheckProject(RustAnalyzerExec):
    session_name = "rust-analyzer"
    check_phrase = "cargo check"

    def run(self, edit: sublime.Edit) -> None:
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        params = text_document_position_params(self.view, self.view.sel()[0].b)
        session.send_request(Request("experimental/runnables", params), self.on_result)

    def on_result(self, payload: List[Any]) -> None:
        self.run_termius(self.check_phrase, payload)


class RustAnalyzerTestProject(RustAnalyzerExec):
    session_name = "rust-analyzer"
    check_phrase = "cargo test"

    def run(self, edit: sublime.Edit) -> None:
        params = text_document_position_params(self.view, self.view.sel()[0].b)
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        session.send_request(Request("experimental/runnables", params), self.on_result)

    def on_result(self, payload: List[Runnable]) -> None:
        self.run_termius(self.check_phrase, payload)


def plugin_loaded() -> None:
    register_plugin(RustAnalyzer)


def plugin_unloaded() -> None:
    unregister_plugin(RustAnalyzer)
