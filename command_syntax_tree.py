from __future__ import annotations

from functools import partial
from LSP.plugin import Error
from LSP.plugin import LspTextCommand
from LSP.plugin import Promise
from LSP.plugin import Request
from LSP.plugin import run_coroutine
from LSP.plugin.core.tree_view import new_tree_view_sheet
from LSP.plugin.core.tree_view import TreeDataProvider
from LSP.plugin.core.tree_view import TreeItem
from LSP.plugin.core.views import text_document_position_params
from LSP.protocol import NotRequired
from LSP.protocol import Range
from typing import Any
from typing import cast
from typing import Literal
from typing import Tuple
from typing import TypedDict
from typing import Union
import json
import sublime
import sublime_plugin


class Offsets(TypedDict):
    start: int
    end: int

class InnerNode(TypedDict):
    range: Range
    offsets: Offsets

class SyntaxNode(TypedDict):
    type: Literal['Node']
    kind: str
    offsets: Offsets
    range: Range
    # This element's position within a Rust string literal, if it's inside of one.
    inner: InnerNode | None
    parent: SyntaxElement | None
    children: list[SyntaxElement]

class SyntaxToken(TypedDict):
    type: Literal['Token']
    kind: str
    range: Range
    offsets: Offsets
    # This element's position within a Rust string literal, if it's inside of one.
    inner: InnerNode | None
    parent: SyntaxElement | None

SyntaxElement = Union[SyntaxNode, SyntaxToken]

class RawNode(TypedDict):
    type: Literal['Node']
    kind: str
    start: Tuple[int, int, int]
    end: Tuple[int, int, int]
    istart: NotRequired[Tuple[int, int, int]]
    iend: NotRequired[Tuple[int, int, int]]
    children: list[SyntaxElement]

class RawToken(TypedDict):
    type: Literal['Token']
    kind: str
    start: Tuple[int, int, int]
    end: Tuple[int, int, int]
    istart: NotRequired[Tuple[int, int, int]]
    iend: NotRequired[Tuple[int, int, int]]

RawElement = Union[RawNode, RawToken]


def parseSyntaxTree(value: str) -> SyntaxElement:

    def object_hook(value: RawElement) -> SyntaxElement:
        if value['type'] != 'Node' and value['type'] != 'Token':
            # This is something other than a RawElement.
            return value

        startOffset, startLine, startCol = value['start']
        endOffset, endLine, endCol = value['end']
        range: Range = {
            'start': {
                'line': startLine,
                'character': startCol,
            },
            'end': {
                'line': endLine,
                'character': endCol
            }
        }
        offsets: Offsets = {
            'start': startOffset,
            'end': endOffset,
        }

        inner: InnerNode | None = None
        if (istart := value.get('istart')) and (iend := value.get('iend')):
            istartOffset, istartLine, istartCol = istart
            iendOffset, iendLine, iendCol = iend
            inner = {
                'offsets': {
                    'start': istartOffset,
                    'end': iendOffset,
                },
                'range': {
                    'start': {
                        'line': istartLine,
                        'character': istartCol
                    },
                    'end': {
                        'line': iendLine,
                        'character': iendCol
                    }
                }
            }

        if value['type'] == 'Node':
            result: SyntaxNode = {
                'type': value['type'],
                'kind': value['kind'],
                'offsets': offsets,
                'range': range,
                'inner': inner,
                'children': value.get('children', []),
                'parent': None,
            }

            for child in result['children']:
                child['parent'] = result

            return result
        else:
            return {
                'type': value['type'],
                'kind': value['kind'],
                'offsets': offsets,
                'range': range,
                'inner': inner,
                'parent': None,
            }

    return json.loads(value, object_hook=lambda v: object_hook(cast('RawElement', v)))


class SyntaxTreeProvider(TreeDataProvider):

    def __init__(self, root_element: SyntaxElement, view_id: int) -> None:
        self.root_element = root_element
        self.view_id = view_id

    def get_children(self, element: SyntaxElement | None) -> Promise[list[SyntaxElement]]:
        if element is None:
            return Promise.resolve([self.root_element])
        return Promise.resolve(element.get('children', []))

    def get_tree_item(self, element: SyntaxElement) -> TreeItem:
        inner = element.get('inner', {})
        offsets = inner['offsets'] if inner else element['offsets']
        offsets_text = f'{offsets["start"]}..{offsets["end"]}'
        return TreeItem(
            label=f'{element["kind"]}',
            description=f'({element["type"]} - {offsets_text})',
            action_command=('rust_analyzer_syntax_tree_click_node', {
                'view_id': self.view_id,
                'range': element['range'],
            })
        )


class RustAnalyzerSyntaxTreeCommand(LspTextCommand):

    def is_enabled(self) -> bool:
        selection = self.view.sel()
        if len(selection) == 0:
            return False
        return super().is_enabled()

    def run(self, edit: sublime.Edit) -> None:
        run_coroutine(self._run())

    async def _run(self) -> None:
        session = self.session_by_name(self.session_name)
        if session is None:
            return
        params = text_document_position_params(self.view, self.view.sel()[0].b)
        sublime.set_timeout(
            partial(self.on_result, await session.request(Request("rust-analyzer/viewSyntaxTree", params)))
        )

    def on_result(self, out: str | Error) -> None:
        if isinstance(out, Error):
            sublime.error_message(f"Error loading syntax tree: {out}")
            return
        window = self.view.window()
        if window is None:
            return
        sheet_name = 'Syntax Tree'
        root_element = parseSyntaxTree(out)
        data_provider = SyntaxTreeProvider(root_element, self.view.id())
        new_tree_view_sheet(window, sheet_name, data_provider, sheet_name, flags=sublime.NewFileFlags.ADD_TO_SELECTION)


class RustAnalyzerSyntaxTreeClickNode(sublime_plugin.WindowCommand):

    def run(self, view_id: int, range: Range) -> None:
        if view := self.find_view_id(view_id):
            view.run_command('rust_analyzer_syntax_tree_select_node_in_view', {'range': cast('dict[str, Any]', range)})

    def find_view_id(self, view_id) -> sublime.View | None:
        for view in self.window.views():
            if view.id() == view_id:
                return view
        return None


class RustAnalyzerSyntaxTreeSelectNodeInView(LspTextCommand):

    def run(self, _: sublime.Edit, *, range: Range) -> None:
        view = self.view
        selection = view.sel()
        selection.clear()
        start = range['start']
        end = range['end']
        region = sublime.Region(view.text_point_utf16(start['line'], start['character']),
                                view.text_point_utf16(end['line'], end['character']),)
        selection.add(region)
        view.show_at_center(region)

