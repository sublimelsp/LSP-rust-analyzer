from __future__ import annotations

from LSP.plugin import apply_text_edits
from LSP.plugin import Error
from LSP.plugin import LspTextCommand
from LSP.plugin import Request
from LSP.plugin import run_coroutine
from LSP.plugin.core.views import first_selection_region
from LSP.plugin.core.views import region_to_range
from LSP.plugin.core.views import text_document_identifier
from LSP.protocol import InsertTextFormat
from LSP.protocol import NotRequired
from LSP.protocol import Range
from LSP.protocol import SnippetTextEdit
from LSP.protocol import TextDocumentIdentifier
from LSP.protocol import TextEdit
from typing import List
from typing import Literal
from typing import TypedDict
from typing import Union
import re
import sublime


class JoinLinesRequest:

    class ParamsType(TypedDict):
        textDocument: TextDocumentIdentifier
        ranges: list[Range]

    Type = 'experimental/joinLines'
    ReturnType = List[TextEdit]


class RASnippetTextEdit(TextEdit):
    insertTextFormat: NotRequired[InsertTextFormat]


class MoveItemRequest:

    class ParamsType(TypedDict):
        textDocument: TextDocumentIdentifier
        range: Range
        direction: MoveItemRequest.Direction

    Type = 'experimental/moveItem'
    Direction = Literal['Up', 'Down']
    ReturnType = List[Union[RASnippetTextEdit, SnippetTextEdit]]


class RustAnalyzerJoinLinesCommand(LspTextCommand):

    def run(self, edit: sublime.Edit) -> None:
        run_coroutine(self.make_request())

    async def make_request(self) -> None:
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        session_view = session.session_view_for_view_async(self.view)
        if not session_view:
            return
        view_listener = session_view.listener()
        if not view_listener:
            return
        params: JoinLinesRequest.ParamsType = {
            'textDocument': text_document_identifier(self.view),
            'ranges': [region_to_range(self.view, region) for region in self.view.sel()],
        }
        request: Request[JoinLinesRequest.ParamsType, JoinLinesRequest.ReturnType] = Request(JoinLinesRequest.Type, params)
        document_version = self.view.change_count()
        await view_listener.purge_changes()
        edits = await session.request(request)
        if isinstance(edits, Error):
            sublime.status_message(
                f'Error handling the "{JoinLinesRequest.Type}" request. Falling back to native join.')
            self.view.run_command('join_lines')
            return
        await apply_text_edits(self.view, edits, required_view_version=document_version)


class RustAnalyzerMoveItemCommand(LspTextCommand):

    def run(self, edit: sublime.Edit, direction: MoveItemRequest.Direction | None = None) -> None:
        if direction not in ('Up', 'Down'):
            sublime.status_message('Error running command: direction must be either "Up" or "Down".')
            return
        run_coroutine(self.make_request(direction))

    async def make_request(self, direction: MoveItemRequest.Direction) -> None:
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
        params: MoveItemRequest.ParamsType = {
            'textDocument': text_document_identifier(self.view),
            'range': region_to_range(self.view, first_selection),
            'direction': direction,
        }
        request: Request[MoveItemRequest.ParamsType, MoveItemRequest.ReturnType] = Request(MoveItemRequest.Type, params)
        document_version = self.view.change_count()
        await view_listener.purge_changes()
        edits = await session.request(request)
        if document_version != self.view.change_count():
            return
        if isinstance(edits, Error):
            sublime.status_message(f'Error handling the "{MoveItemRequest.Type}" request.')
            return
        if not edits:
            sublime.status_message('Did not find anything to move.')
            return
        # Convert custom TextEdit with placeholder into SnippetTextEdit
        for i, edit in enumerate(edits):
            if (
                'insertTextFormat' in edit and edit.get('insertTextFormat') == InsertTextFormat.Snippet
                # Only apply if text actually contains unexpected `$` since RA tends to also mark non-snippets as such.
                and re.search(r'(^|[^\\])\$', edit['newText'])
            ):
                edits[i] = {'range': edit['range'], 'snippet': {'kind': 'snippet', 'value': edit['newText']}}
        await apply_text_edits(self.view, edits)
