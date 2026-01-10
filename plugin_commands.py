from __future__ import annotations
from .plugin import RustAnalyzerCommand
from LSP.plugin import apply_text_edits
from LSP.plugin import Request
from LSP.plugin.core.protocol import Error
from LSP.plugin.core.views import first_selection_region
from LSP.plugin.core.views import region_to_range
from LSP.plugin.core.views import text_document_identifier
from LSP.protocol import Range
from LSP.protocol import TextDocumentIdentifier
from LSP.protocol import TextEdit
from typing import List, Literal, TypedDict
import sublime


class JoinLinesRequest:

    class ParamsType(TypedDict):
        textDocument: TextDocumentIdentifier
        ranges: List[Range]

    Type = 'experimental/joinLines'
    ReturnType = List[TextEdit]


class MoveItemRequest:

    class ParamsType(TypedDict):
        textDocument: TextDocumentIdentifier
        range: Range
        direction: MoveItemRequest.Direction

    Type = 'experimental/moveItem'
    Direction = Literal['Up', 'Down']
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

    def on_result_async(self, edits: JoinLinesRequest.ReturnType | Error, document_version: int) -> None:
        if isinstance(edits, Error):
            sublime.status_message(
                f'Error handling the "{JoinLinesRequest.Type}" request. Falling back to native join.')
            self.view.run_command('join_lines')
            return
        apply_text_edits(self.view, edits, required_view_version=document_version)


class RustAnalyzerMoveItemCommand(RustAnalyzerCommand):

    def run(self, edit: sublime.Edit, direction: MoveItemRequest.Direction | None = None) -> None:
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

    def on_result_async(self, edits: MoveItemRequest.ReturnType | Error, document_version: int) -> None:
        if document_version != self.view.change_count():
            return
        if isinstance(edits, Error):
            sublime.status_message(f'Error handling the "{MoveItemRequest.Type}" request.')
            return
        if not edits:
            sublime.status_message('Did not find anything to move.')
            return
        apply_text_edits(self.view, edits, process_placeholders=True)
