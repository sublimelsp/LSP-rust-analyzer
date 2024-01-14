from .plugin import RustAnalyzerCommand
from LSP.plugin import apply_text_edits
from LSP.plugin import Request
from LSP.plugin.core.protocol import Error
from LSP.plugin.core.protocol import Range
from LSP.plugin.core.protocol import TextDocumentIdentifier
from LSP.plugin.core.protocol import TextEdit
from LSP.plugin.core.typing import List, TypedDict, Union
from LSP.plugin.core.views import region_to_range
from LSP.plugin.core.views import text_document_identifier
import sublime


class JoinLinesRequest:
    Type = 'experimental/joinLines'
    ParamsType = TypedDict('ParamsType', {
        'textDocument': TextDocumentIdentifier,
        'ranges': List[Range],
    })
    ReturnType = List[TextEdit]


class RustAnalyzerJoinLinesCommand(RustAnalyzerCommand):

    def run(self, edit: sublime.Edit) -> None:
        sublime.set_timeout_async(self.make_request_async)

    def make_request_async(self) -> None:
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        session_view = session.session_view_for_view_async(self.view)
        if not session_view:
            return
        view_listener = session_view.listener()
        if not view_listener:
            return
        params = {
            'textDocument': text_document_identifier(self.view),
            'ranges': [region_to_range(self.view, region) for region in self.view.sel()],
        }  # type: JoinLinesRequest.ParamsType
        request = Request(JoinLinesRequest.Type, params)  # type: Request[JoinLinesRequest.ReturnType]
        document_version = self.view.change_count()
        view_listener.purge_changes_async()
        session.send_request_task(request).then(lambda result: self.on_result_async(result, document_version))

    def on_result_async(self, edits: Union[JoinLinesRequest.ReturnType, Error], document_version: int) -> None:
        if isinstance(edits, Error):
            print('[{}] Error handling the "{}" request. Falling back to native join.'.format(
                self.session_name, JoinLinesRequest.Type))
            self.view.run_command('join_lines')
            return
        apply_text_edits(self.view, edits, required_view_version=document_version)
