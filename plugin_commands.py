from .plugin import RustAnalyzerCommand
from LSP.plugin import Request
from LSP.plugin.core.protocol import Error
from LSP.plugin.core.protocol import Range
from LSP.plugin.core.protocol import TextDocumentIdentifier
from LSP.plugin.core.protocol import TextEdit
from LSP.plugin.core.typing import List, TypedDict, Union
from LSP.plugin.core.views import region_to_range
from LSP.plugin.core.views import text_document_identifier
from LSP.plugin.formatting import apply_text_edits_to_view
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
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        params = {
            'textDocument': text_document_identifier(self.view),
            'ranges': [region_to_range(self.view, region) for region in self.view.sel()],
        }  # type: JoinLinesRequest.ParamsType
        session.send_request(Request(JoinLinesRequest.Type, params), self.on_result_async)

    def on_result_async(self, edits: Union[JoinLinesRequest.ReturnType, Error]) -> None:
        if isinstance(edits, Error):
            print('[{}] Error handling the "{}" request. Falling back to native join.'.format(
                self.session_name, JoinLinesRequest.Type))
            self.view.run_command('join_lines')
            return
        if edits:
            apply_text_edits_to_view(edits, self.view)
