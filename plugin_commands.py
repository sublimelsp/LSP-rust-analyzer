from .plugin import RustAnalyzerCommand
from LSP.plugin import apply_text_edits
from LSP.plugin import Request
from LSP.plugin.core.protocol import Error
from LSP.plugin.core.protocol import Range
from LSP.plugin.core.protocol import TextDocumentIdentifier
from LSP.plugin.core.protocol import TextEdit
from LSP.plugin.core.typing import List, Literal, Optional, TypedDict, Union
from LSP.plugin.core.views import first_selection_region
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


class MoveItemRequest:
    Type = 'experimental/moveItem'
    Direction = Literal['Up', 'Down']
    ParamsType = TypedDict('ParamsType', {
        'textDocument': TextDocumentIdentifier,
        'range': Range,
        'direction': Direction,
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
            sublime.status_message('Error handling the "{}" request. Falling back to native join.'.format(
                JoinLinesRequest.Type))
            self.view.run_command('join_lines')
            return
        apply_text_edits(self.view, edits, required_view_version=document_version)


class RustAnalyzerMoveItemCommand(RustAnalyzerCommand):

    def run(self, edit: sublime.Edit, direction: Optional[MoveItemRequest.Direction] = None) -> None:
        if direction not in ('Up', 'Down'):
            sublime.status_message('Error running command: direction must be either "Up" or "Down".')
            return
        sublime.set_timeout_async(lambda: self.make_request_async(direction))

    def make_request_async(self, direction: MoveItemRequest.Direction) -> None:
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        session_view = session.session_view_for_view_async(self.view)
        if not session_view:
            return
        view_listener = session_view.listener()
        if not view_listener:
            return
        first_selection = first_selection_region(self.view)
        if first_selection is None:
            return
        params = {
            'textDocument': text_document_identifier(self.view),
            'range': region_to_range(self.view, first_selection),
            'direction': direction,
        }  # type: MoveItemRequest.ParamsType
        request = Request(MoveItemRequest.Type, params)  # type: Request[MoveItemRequest.ReturnType]
        document_version = self.view.change_count()
        view_listener.purge_changes_async()
        session.send_request_task(request).then(lambda result: self.on_result_async(result, document_version))

    def on_result_async(self, edits: Union[MoveItemRequest.ReturnType, Error], document_version: int) -> None:
        if document_version != self.view.change_count():
            return
        if isinstance(edits, Error):
            sublime.status_message('Error handling the "{}" request.'.format(MoveItemRequest.Type))
            return
        if not edits:
            sublime.status_message('Did not find anything to move.')
            return
        apply_text_edits_to_view(edits, self.view, process_snippets=True)
