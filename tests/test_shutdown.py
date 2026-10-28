"""Application-owned scheduler/client shutdown, including modal Ctrl-C."""

from unittest.mock import AsyncMock, Mock

import pytest

from usage_tui.accounts import AccountManagerScreen
from usage_tui.app import InformationScreen, UsageApp


@pytest.mark.parametrize("scenario", ["healthy", "errors"])
@pytest.mark.parametrize("modal", ["?", "a"])
async def test_demo_ctrl_c_from_modal_stops_source_once(scenario, modal, monkeypatch):
    app = UsageApp(mode="demo", scenario=scenario)
    source = app.scheduler
    stop = AsyncMock(wraps=source.stop)
    monkeypatch.setattr(source, "stop", stop)
    async with app.run_test(size=(40, 12)) as pilot:
        await pilot.press(modal)
        expected = InformationScreen if modal == "?" else AccountManagerScreen
        assert isinstance(app.screen, expected)
        await pilot.press("ctrl+c")
    assert not app.is_running
    assert app._usage_closed
    stop.assert_awaited_once_with()
    await app.on_unmount()
    stop.assert_awaited_once_with()
    with pytest.raises(RuntimeError, match="stopped"):
        await source.start()


async def test_live_unmount_stops_scheduler_before_closing_factory_and_is_idempotent():
    events = []

    async def stop():
        events.append("stop")

    async def close():
        events.append("close")

    factory = Mock()
    factory.aclose = AsyncMock(side_effect=close)
    scheduler = Mock()
    scheduler.stop = AsyncMock(side_effect=stop)
    app = UsageApp(mode="live", scheduler_factory=factory)
    app.scheduler = scheduler
    await app.on_unmount()
    await app.on_unmount()
    assert events == ["stop", "close"]
    scheduler.stop.assert_awaited_once_with()
    factory.aclose.assert_awaited_once_with()
    assert app._usage_closed


async def test_factory_is_closed_even_when_scheduler_stop_raises():
    factory = Mock()
    factory.aclose = AsyncMock()
    app = UsageApp(mode="live", scheduler_factory=factory)
    app.scheduler = Mock()
    app.scheduler.stop = AsyncMock(side_effect=RuntimeError("synthetic stop failure"))
    with pytest.raises(RuntimeError, match="synthetic stop failure"):
        await app.on_unmount()
    factory.aclose.assert_awaited_once_with()
    assert app._usage_closed


async def test_late_publication_after_shutdown_cannot_restore_stale_rows():
    app = UsageApp(mode="demo")
    async with app.run_test() as pilot:
        await pilot.pause()
        snapshot = next(iter(app.snapshots.values()))
        await pilot.press("q")
    app.snapshots.clear()
    app.publish_snapshot(snapshot)
    assert app.snapshots == {}
