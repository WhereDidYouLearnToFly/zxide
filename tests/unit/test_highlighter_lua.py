"""The highlighter switches languages inside a LUA/ENDLUA block.

An sjasmplus source can contain Lua, and zxide's own memory dumper generates exactly that
to write a snapshot with a correct register header. Highlighting the block as assembly is
worse than not highlighting it: Lua's ``--`` comments read as subtraction, and its
keywords as labels.

The mechanism is a block state carried between lines -- the only way a line-at-a-time
QSyntaxHighlighter can know it is halfway through something that began earlier -- so these
tests are mostly about the state machine rather than about colours.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtGui import QTextDocument  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from zxemu_ui.z80_highlighter import (  # noqa: E402
    _STATE_ASM,
    _STATE_LUA,
    Z80Highlighter,
)


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _states(qapp, source: str) -> list[int]:
    """The block state left after each line, which is what drives the switching."""
    document = QTextDocument()
    highlighter = Z80Highlighter(document)
    document.setPlainText(source)
    # Without this the highlighter only runs on blocks Qt decides need painting, and an
    # offscreen document paints nothing -- every state would read back as -1.
    highlighter.rehighlight()
    states = []
    block = document.firstBlock()
    while block.isValid():
        states.append(block.userState())
        block = block.next()
    return states


def test_lines_inside_a_lua_block_are_marked_as_lua(qapp):
    states = _states(qapp, "\n".join([
        "    org $8000",
        "    LUA",
        "        local x = 1",
        "    ENDLUA",
        "    ret",
    ]))
    assert states == [_STATE_ASM, _STATE_LUA, _STATE_LUA, _STATE_ASM, _STATE_ASM]


def test_the_endlua_line_itself_is_assembly(qapp):
    """It is the assembler's directive, not Lua's -- so it colours like `org` or `db`."""
    states = _states(qapp, "    LUA\n        local x = 1\n    ENDLUA")
    assert states[-1] == _STATE_ASM


def test_a_pass_qualified_opener_still_opens_the_block(qapp):
    """sjasmplus allows `LUA PASS1` / `LUA ALLPASS`, so matching the whole line fails."""
    for opener in ("    LUA PASS1", "    LUA ALLPASS", "    lua"):
        states = _states(qapp, f"{opener}\n        local x = 1\n    ENDLUA")
        assert states[1] == _STATE_LUA, opener


def test_assembly_outside_the_block_is_unaffected(qapp):
    states = _states(qapp, "\n".join([
        "; a comment",
        "start:",
        "    ld a,$07",
        "    out ($fe),a",
    ]))
    assert states == [_STATE_ASM] * 4


def test_a_lua_block_that_is_never_closed_stays_lua(qapp):
    """A half-written block should not silently revert to assembly colouring partway."""
    states = _states(qapp, "    LUA\n        local a = 1\n        local b = 2")
    assert states == [_STATE_LUA, _STATE_LUA, _STATE_LUA]


def test_the_dumpers_own_generated_block_is_recognised(qapp):
    """The case this exists for: what the memory dumper actually emits."""
    from zxemu_core.debug import dumper

    state = {
        "pc": 0x8000, "sp": 0x7F00, "af": 0x5A41, "af2": 0x7780,
        "bc": 0x1234, "de": 0x5678, "hl": 0x9ABC,
        "bc2": 0x1111, "de2": 0x2222, "hl2": 0x3333,
        "ix": 0, "iy": 0, "i": 0x39, "r": 0, "im": 2, "iff": True,
        "border": 2, "port_7ffd": None, "ram_bank": None,
    }
    source = "\n".join(["    org $8000"] + dumper.render_snapshot_lua(state, False, "x.sna"))

    states = _states(qapp, source)

    assert _STATE_LUA in states, "the generated Lua block was not detected"
    # ...and it closes again, so anything after it is assembly.
    assert states[-1] == _STATE_ASM
