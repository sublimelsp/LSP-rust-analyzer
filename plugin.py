from LSP.plugin import AbstractPlugin
from LSP.plugin import register_plugin
from LSP.plugin import unregister_plugin
import gzip
import os
import shutil
import sublime
import urllib.request

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
        return os.path.join(cls.storage_path(), "LSP-{}".format(cls.name()))

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
            shutil.rmtree(cls.basedir(), ignore_errors=True)
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
