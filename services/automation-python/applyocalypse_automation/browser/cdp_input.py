"""The CDP ``Input`` domain, spoken through a Patchright CDP session.

``human_typing``, ``trusted_click`` and ``human_scroll`` build their events as
calls on an input domain (``dispatch_key_event(...)``, ``insert_text(...)``,
``dispatch_mouse_event(...)``) and hand each result to a target's ``send``. They
were written against nodriver, whose ``cdp.input_`` module returns a command
object from those calls. Patchright has no typed CDP bindings; it has
``CDPSession.send(method, params)``. This module is the difference: the same
calls return a ``(method, params)`` pair, and ``CdpTarget.send`` delivers it.

Nothing here is Windows- or macOS-specific. The selectAll that clears a field is
sent as an editing command by name rather than as a platform shortcut, so it
behaves the same whether the platform modifier is Ctrl or Cmd.
"""

from __future__ import annotations

from typing import Any

Command = tuple[str, dict[str, Any]]


def _camel(name: str) -> str:
    """``windows_virtual_key_code`` -> ``windowsVirtualKeyCode``; ``type_`` -> ``type``."""
    head, *rest = name.rstrip("_").split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def _params(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {_camel(key): value for key, value in kwargs.items() if value is not None}


class InputDomain:
    """Builds ``Input.*`` commands with the call shapes the helpers already use."""

    # CDP takes the button as its name; the helpers wrap it in this type first.
    MouseButton = str

    @staticmethod
    def dispatch_key_event(type_: str, **kwargs: Any) -> Command:
        return ("Input.dispatchKeyEvent", _params({"type_": type_, **kwargs}))

    @staticmethod
    def dispatch_mouse_event(type_: str, **kwargs: Any) -> Command:
        return ("Input.dispatchMouseEvent", _params({"type_": type_, **kwargs}))

    @staticmethod
    def insert_text(text: str) -> Command:
        return ("Input.insertText", {"text": text})


INPUT_DOMAIN = InputDomain()


class CdpTarget:
    """A page's CDP session, with the ``send(command)`` the helpers call.

    Input goes to the top-level page even for a control inside a cross-origin
    frame. Chrome routes mouse and wheel events by hit-testing the root widget
    and keyboard events to whichever frame holds focus, which is how Playwright's
    own keyboard and mouse reach embedded forms.
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    async def send(self, command: Command) -> Any:
        method, params = command
        return await self._session.send(method, params)
