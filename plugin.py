from LSP.plugin import AbstractPlugin
from LSP.plugin import register_plugin
from LSP.plugin import unregister_plugin
from LSP.plugin.core.typing import List, Optional
from LSP.plugin import WorkspaceFolder
from LSP.plugin import ClientConfig
from LSP.plugin.core.logging import debug
import sublime
from os.path import realpath
import shutil


name = "rust-analyzer"

def which_realpath(exe: str) -> Optional[str]:
    path = shutil.which(exe)
    if path:
        return realpath(path)
    return None

class RustAnalyzer(AbstractPlugin):

    

    @classmethod
    def name(cls) -> str:
        return name

    @classmethod
    def can_start(
        cls,
        window: sublime.Window,
        initiating_view: sublime.View,
        workspace_folders: List[WorkspaceFolder],
        configuration: ClientConfig,
    ) -> Optional[str]:
        rust_analyzer_binary = None
        flutter_bin = which_realpath("rust-analyzer")
        if flutter_bin:
            rust_analyzer_binary = flutter_bin
        if not rust_analyzer_binary:
            rust_analyzer_binary = configuration.settings.get("rust-analyzer.server.path")

        if not rust_analyzer_binary:
            return "Unable to find rust-analyzer binary. Should be on path or specified in the LSP-rust-analyzer rust-analyzer.server.path"
        configuration.command = [rust_analyzer_binary]
        debug("binary at {}".format(rust_analyzer_binary))
        return None

    @classmethod
    def on_pre_start(cls, window: sublime.Window, initiating_view: sublime.View,
                     workspace_folders: List[WorkspaceFolder], configuration: ClientConfig) -> Optional[str]:
        debug("Starting......")
        debug(configuration.settings)
        return None






def plugin_loaded() -> None:
    register_plugin(RustAnalyzer)


def plugin_unloaded() -> None:
    unregister_plugin(RustAnalyzer)
