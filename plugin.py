from LSP.plugin.core.protocol import Location
from LSP.plugin import AbstractPlugin
from LSP.plugin import register_plugin
from LSP.plugin import Request
from LSP.plugin import Session
from LSP.plugin import unregister_plugin
from LSP.plugin.core.protocol import Range, RangeLsp
from LSP.plugin.core.registry import LspTextCommand
from LSP.plugin.core.views import text_document_position_params, text_document_identifier
from LSP.plugin.core.types import debounced
from LSP.plugin.core.types import FEATURES_TIMEOUT
from LSP.plugin.core.typing import Optional, Union, List, Tuple, Any, TypedDict, Mapping, Callable, Dict
from LSP.plugin.core.views import point_to_offset
from LSP.plugin.core.views import uri_from_view
from html import escape as html_escape
import gzip
import os
import shutil
import sublime
import sublime_plugin
import weakref
import urllib.request
import functools


try:
    import Terminus  # type: ignore
except ImportError:
    Terminus = None


try:
    import Terminus  # type: ignore
except ImportError:
    Terminus = None


SESSION_NAME = "rust-analyzer"

# Update this single git tag to download a newer version.
# After changing this tag, go through the server settings again to see
# if any new server settings are added or old ones removed.
TAG = "2021-07-12"

URL = "https://github.com/rust-analyzer/rust-analyzer/releases/download/{tag}/rust-analyzer-{arch}-{platform}.gz"  # noqa: E501

InlayHint = TypedDict("InlayHint", {
    "kind": str,
    "range": RangeLsp,
    "label": str,
}, total=True)

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
    return sublime.load_settings('LSP-rust-analyzer.sublime-settings').get("settings", {}).get(key, default)


def platform() -> str:
    if sublime.platform() == "windows":
        return "pc-windows-msvc"
    elif sublime.platform() == "osx":
        return "apple-darwin"
    else:
        return "unknown-linux-gnu"


def inlay_hint_css(view: sublime.View) -> str:
    style = view.style_for_scope("comment")
    rules = [
        "color: {};".format(style["foreground"]),
    ]

    css = """
    body {{
        padding: 0px;
        margin: 0px;
        border: 0px;
        font-size: 0.8em;
    }}

    .rust-analyzer-inlay-hints {{
        {0}
    }}
    """
    return css.format('\n'.join(rules))


def inlay_hint_to_phantom(view: sublime.View, css: str, hint: InlayHint) -> sublime.Phantom:
    rng = Range.from_lsp(hint["range"])
    html = """
    <body id="rust-analyzer-inlay-hints">
        <style>{css}</style>
        <div class="rust-analyzer-inlay-hints">
            {label}
        </div>
    </body>
    """

    label = html_escape(hint["label"])
    if hint["kind"] == "TypeHint":
        # For a type hint, the end range is where you want to put it
        region = sublime.Region(point_to_offset(rng.end, view))
        label = ": {}".format(label)
    elif hint["kind"] == "ParameterHint":
        # For parameter hints, you actually want it to start where it's started
        region = sublime.Region(point_to_offset(rng.start, view))
        label = "{}: ".format(label)
    else:
        # The last kind is ChainingHint, we want those at the end too
        region = sublime.Region(point_to_offset(rng.end, view))
        label = ": {}".format(label)

    html = html.format(css=css, label=label)
    return sublime.Phantom(region, html, sublime.LAYOUT_INLINE)


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
    main_cargo = shutil.which("cargo")
    if not main_cargo:
        sublime.error_message('Cannot find "cargo" on path.')
        return
    main_cargo_path = '"{}"'.format(main_cargo)
    for runnable in filtered_runnables:
        if runnable["args"]["overrideCargo"]:
            cargo_path = runnable["args"]["overrideCargo"]
        else:
            cargo_path = main_cargo_path
        command_to_run = [cargo_path] + runnable["args"]["cargoArgs"]
        if runnable["args"]["cargoExtraArgs"]:
            command_to_run += runnable["args"]["cargoExtraArgs"]
        if runnable["args"]["executableArgs"]:
            command_to_run += ['--'] + runnable["args"]["executableArgs"]
        args = {
            "title": runnable["label"],
            "shell_cmd": " ".join(command_to_run),
            "cwd": runnable["args"]["workspaceRoot"],
            "auto_close": get_setting(view, "rust-analyzer.terminusAutoClose", False)
        }
        if get_setting(view, "rust-analyzer.terminusUsePanel", False):
            args["panel_name"] = runnable["label"]
        window.run_command("terminus_open", args)


class RustAnalyzer(AbstractPlugin):

    plugin_mapping = weakref.WeakValueDictionary()  # type: weakref.WeakValueDictionary[int, RustAnalyzer]

    def __init__(self, session: 'weakref.ref[Session]') -> None:
        super().__init__(session)
        s = session()
        if s:
            self.plugin_mapping[s.window.id()] = self

    @classmethod
    def plugin_from_view(cls, view: sublime.View) -> Optional['RustAnalyzer']:
        window = view.window()
        if window is None:
            return None
        self = cls.plugin_mapping.get(window.id())
        if self is None or not self.is_valid_for_view(view):
            return None
        return self

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
        if command["command"] not in ("rust-analyzer.runSingle", "rust-analyzer.runDebug"):
            open_runnables_in_terminus(sublime.active_window(), command["arguments"])
            done_callback()
            return True
        return False

    def is_valid_for_view(self, view: sublime.View) -> bool:
        session = self.weaksession()
        if not session or not session.session_view_for_view_async(view):
            return False
        return True

    def request_inlay_hints_async(self, view: sublime.View) -> None:
        if not get_setting(view, "rust-analyzer.inlayHints.enable", True):
            return

        session = self.weaksession()
        if session is None:
            return
        params = {
            "textDocument": text_document_identifier(view),
        }

        session.send_request_async(
            Request("rust-analyzer/inlayHints", params),
            functools.partial(self.on_inlay_hints_async, view)
        )

    def on_inlay_hints_async(self, view: sublime.View, hints: List[InlayHint]) -> None:
        session = self.weaksession()
        if session is None:
            return
        buffer = session.get_session_buffer_for_uri_async(uri_from_view(view))
        if not buffer:
            return
        key = "_lsp_rust_analyzer_inlay_hints"
        phantom_set = getattr(buffer, key, None)
        if phantom_set is None:
            phantom_set = sublime.PhantomSet(view, key)
            setattr(buffer, key, phantom_set)
        css = inlay_hint_css(view)
        phantoms = [inlay_hint_to_phantom(view, css, hint) for hint in hints]
        sublime.set_timeout(
            functools.partial(
                self.present_inlay_hints,
                view,
                phantom_set,
                phantoms
            )
        )

    def present_inlay_hints(
        self,
        view: sublime.View,
        phantom_set: sublime.PhantomSet,
        phantoms: List[sublime.Phantom]
    ) -> None:
        if not view.is_valid():
            return
        phantom_set.update(phantoms)


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


class EventListener(sublime_plugin.ViewEventListener):
    def __init__(self, view: sublime.View) -> None:
        super().__init__(view)
        self._stored_region = sublime.Region(-1, -1)

    # This trick comes from the parent LSP repo
    def _update_stored_region_async(self) -> Tuple[bool, sublime.Region]:
        sel = self.view.sel()
        if not sel:
            return False, sublime.Region(-1, -1)
        region = sel[0]
        if self._stored_region != region:
            self._stored_region = region
            return True, region
        return False, sublime.Region(-1, -1)

    def on_modified_async(self) -> None:
        plugin = RustAnalyzer.plugin_from_view(self.view)
        if plugin is None:
            return
        different, region = self._update_stored_region_async()
        if not different:
            return
        debounced(
            functools.partial(plugin.request_inlay_hints_async, self.view),
            FEATURES_TIMEOUT,
            lambda: self._stored_region == region,
            async_thread=True,
        )

    def on_load_async(self) -> None:
        plugin = RustAnalyzer.plugin_from_view(self.view)
        if plugin is None:
            return
        plugin.request_inlay_hints_async(self.view)

    on_activated_async = on_load_async


def plugin_loaded() -> None:
    register_plugin(RustAnalyzer)


def plugin_unloaded() -> None:
    unregister_plugin(RustAnalyzer)
    RustAnalyzer.plugin_mapping.clear()
