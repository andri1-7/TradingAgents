from pathlib import Path


def test_monitor_service_is_separate_and_does_not_start_bot_polling():
    text = Path('deploy/idx-stockbit-monitor.service').read_text()
    assert 'tradingagents.idx_strategies.monitor' in text
    assert '/srv/alt-whale-tracker/.env' in text
    assert 'Restart=on-failure' in text
    assert 'UMask=0077' in text
    assert 'getUpdates' not in text
    assert 'ExecStartPre=' not in text
