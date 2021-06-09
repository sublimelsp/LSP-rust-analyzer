from LSP.plugin import AbstractPlugin
from LSP.plugin import ClientConfig
from LSP.plugin import register_plugin
from LSP.plugin import unregister_plugin
from LSP.plugin import WorkspaceFolder
from LSP.plugin.core.typing import List, Optional
import shutil
import sublime


class RustAnalyzer(AbstractPlugin):

    @classmethod
    def name(cls) -> str:
        return "rust-analyzer"

    @classmethod
    def can_start(
        cls,
        window: sublime.Window,
        initiating_view: sublime.View,
        workspace_folders: List[WorkspaceFolder],
        configuration: ClientConfig,
    ) -> Optional[str]:
        rust_analyzer_binary = shutil.which("rust-analyzer")
        if not rust_analyzer_binary:
            rust_analyzer_binary = configuration.settings.get("rust-analyzer.server.path")
        if not rust_analyzer_binary:
            return "Unable to find rust-analyzer binary. Should be on the PATH or specified in the 'rust-analyzer.server.path' setting"
        configuration.command = [rust_analyzer_binary]
        return None


def plugin_loaded() -> None:
    register_plugin(RustAnalyzer)


def plugin_unloaded() -> None:
    unregister_plugin(RustAnalyzer)
