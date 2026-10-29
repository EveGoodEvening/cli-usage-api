"""Option list whose enabled options can be dragged to a new position.

The list only reports intent: ``Moved`` carries the dragged option's ID (not its
source index, which a reload can invalidate) and the target index. The owning
screen validates and persists the order. There is no autoscroll; keyboard moves
cover long lists.
"""

from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import OptionList


class ReorderableOptionList(OptionList):
    class Moved(Message):
        """An option was dropped at ``target_index``; the owner decides whether to persist."""

        def __init__(self, account_id: str, target_index: int) -> None:
            super().__init__()
            self.account_id = account_id
            self.target_index = target_index

    class DragStatus(Message):
        """Drag feedback while the drag is active: the hovered drop position."""

        def __init__(self, account_id: str, target: int, total: int) -> None:
            super().__init__()
            self.account_id = account_id
            self.target = target
            self.total = total

    class DragEnded(Message):
        """The drag is over, so Esc no longer cancels it.

        ``reason`` is ``"moved"`` (a ``Moved`` follows), ``"unchanged"`` (dropped on
        its own position), ``"cancelled"`` (Esc) or ``"reloaded"`` (the list was
        rebuilt, for example after another writer's change).
        """

        def __init__(self, account_id: str, reason: str) -> None:
            super().__init__()
            self.account_id = account_id
            self.reason = reason

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.readonly = False
        self._drag_id: str | None = None
        self._drag_origin: int | None = None
        self._drag_target: int | None = None
        self._drag_moved = False
        self._suppress_click = False

    @property
    def dragging(self) -> bool:
        return self._drag_id is not None

    def _line_option(self, y: int, *, clamp: bool) -> int | None:
        """Option index on content line ``y`` (viewport-relative); clamp for drop targets."""
        lines = self._lines
        line = y + self.scroll_offset.y
        if not lines:
            return None
        if clamp:
            line = max(0, min(line, len(lines) - 1))
        elif not 0 <= line < len(lines):
            return None
        return lines[line][0]

    def _index_of(self, option_id: str) -> int | None:
        try:
            return self.get_option_index(option_id)
        except Exception:  # noqa: BLE001 - Textual raises OptionDoesNotExist for a stale ID.
            return None

    def cancel_drag(self, reason: str | None = None) -> None:
        """Forget any drag in progress; a later release cannot reorder.

        With ``reason``, an active drag reports ``DragEnded`` so stale drag feedback
        (and its Esc hint) is replaced.
        """
        if reason is not None and self._drag_id is not None:
            self.post_message(self.DragEnded(self._drag_id, reason))
        self._drag_id = self._drag_origin = self._drag_target = None
        self._drag_moved = False
        if self.app.mouse_captured is self:
            self.release_mouse()

    async def _on_mouse_down(self, event: events.MouseDown) -> None:
        self._suppress_click = False
        if self.readonly or event.button != 1:
            return
        index = event.style.meta.get("option")
        if index is None:
            offset = event.get_content_offset(self)
            index = None if offset is None else self._line_option(offset.y, clamp=False)
        if index is None or not 0 <= index < self.option_count:
            return
        option = self.get_option_at_index(index)
        if option.disabled or option.id is None:
            return
        self._drag_id = option.id
        self._drag_origin = self.highlighted
        self._drag_target = index
        self.capture_mouse()

    async def _on_mouse_move(self, event: events.MouseMove) -> None:
        # The base hover tracking still runs through the MRO.
        if self.readonly or self._drag_id is None or not self.option_count:
            return
        target = self._line_option(event.get_content_offset_capture(self).y, clamp=True)
        if target is None:
            return
        target = max(0, min(target, self.option_count - 1))
        self._drag_moved = self._drag_moved or target != self._drag_target
        self._drag_target = target
        self.highlighted = target
        self.post_message(self.DragStatus(self._drag_id, target, self.option_count))

    async def _on_mouse_up(self, event: events.MouseUp) -> None:
        if self.readonly or self._drag_id is None:
            return
        account_id, target, moved = self._drag_id, self._drag_target, self._drag_moved
        source = self._index_of(account_id)
        reorder = source is not None and target is not None and target != source
        self.cancel_drag("moved" if reorder else "unchanged")
        if reorder:
            self.post_message(self.Moved(account_id, target))
        # A press and release on one row stays an ordinary click. After a drag,
        # Textual synthesizes a Click only for a release over the pressed widget.
        if moved and self.region.contains(event.screen_x, event.screen_y):
            self._suppress_click = True

    async def _on_click(self, event: events.Click) -> None:
        # The base handler still runs through the MRO unless the click ends a drag.
        if self._suppress_click:
            self._suppress_click = False
            event.prevent_default()
            event.stop()

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "escape" and self._drag_id is not None:
            event.prevent_default()
            event.stop()
            account_id = self._drag_id
            origin = self._drag_origin
            self.cancel_drag("cancelled")
            restored = self._index_of(account_id) if origin is None else origin
            if restored is not None and restored < self.option_count:
                self.highlighted = restored
