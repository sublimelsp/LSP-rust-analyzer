from LSP.plugin import AbstractPlugin
from LSP.plugin import register_plugin
from LSP.plugin import Request
from LSP.plugin import unregister_plugin
from LSP.plugin.core.registry import LspTextCommand
from LSP.plugin.core.typing import Optional
from LSP.plugin.core.views import text_document_position_params
import gzip
import os
import shutil
import sublime
import urllib.request

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
            gzipfile = os.path.join(cls.basedir(), "server.gz")
            serverfile = os.path.join(
                cls.basedir(),
                "server.exe" if sublime.platform() == "windows" else "server"
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


class RustAnalyzerOpenDocsCommand(LspTextCommand):
    session_name = "rust-analyzer"

    def is_enabled(self) -> bool:
        if not bool(self.session_by_name(self.session_name)):
            return False

        selection = self.view.sel()
        if len(selection) == 0:
            return False

        return True

    def run(self, edit: sublime.Edit) -> None:
        params = text_document_position_params(self.view, self.view.sel()[0].b)
        session = self.session_by_name(self.session_name)
        session.send_request(Request("experimental/externalDocs", params), self.on_result)

    def on_result(self, url: Optional[str]) -> None:
        window = self.view.window()
        if window is None:
            return

        if url is not None:
            window.run_command("open_url", { "url": url })

def plugin_loaded() -> None:
    register_plugin(RustAnalyzer)


def plugin_unloaded() -> None:
    unregister_plugin(RustAnalyzer)
