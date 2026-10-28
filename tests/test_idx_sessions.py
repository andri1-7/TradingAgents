"""Synthetic calendar only: these times are not verified IDX hours."""
import json
from datetime import date, datetime

import pytest

from tradingagents.idx_strategies.sessions import (
    MissingSession,
    Session,
    decision_windows,
    load_sessions,
)


def test_policy_windows_and_lunch_arithmetic(tmp_path):
    cal = load(tmp_path, payload())
    session = cal.get(date(2026, 10, 23))
    nxt = cal.next_session(session.date)
    day = decision_windows(session, 'day')
    assert day['decision_start'].isoformat() == '2026-10-23T09:30:00+07:00'
    assert day['planned_exit'].isoformat() == '2026-10-23T15:30:00+07:00'
    assert day['entry_deadline'] <= day['planned_exit']
    overnight = decision_windows(session, 'overnight', nxt)
    assert overnight['decision_start'].isoformat() == '2026-10-23T15:15:00+07:00'
    assert overnight['decision_end'] == overnight['decision_start']
    assert overnight['planned_exit'].isoformat() == '2026-10-26T09:30:00+07:00'
    with pytest.raises(MissingSession):
        decision_windows(session, 'overnight')
    with pytest.raises(ValueError):
        decision_windows(session, 'nonsense')
    short = Session(session.date, ((session.open, session.open.replace(minute=20)),))
    with pytest.raises(ValueError):
        decision_windows(short, 'day')
    # First continuous segment lasts 20 min, remainder of opening window is after lunch.
    split = Session(session.date, ((session.open, session.open.replace(minute=20)),
                    (session.open.replace(hour=13), session.close)))
    assert decision_windows(split, 'day')['decision_start'].hour == 13
    assert decision_windows(split, 'day')['decision_start'].minute == 10


def payload():
    return {'source_url': 'https://operator.example/synthetic-v1',
            'retrieved_at': '2026-10-01T00:00:00+00:00', 'timezone': 'Asia/Jakarta',
            'sessions': [{'date': day, 'intervals': [[f'{day}T09:00:00+07:00', f'{day}T12:00:00+07:00'],
                                                   [f'{day}T13:30:00+07:00', f'{day}T15:45:00+07:00']]}
                         for day in ['2026-10-26', '2026-10-23', '2026-10-28']]}


def load(tmp_path, data):
    path = tmp_path / 'synthetic.json'
    path.write_text(json.dumps(data))
    return load_sessions(path)


def test_sorted_immutable_calendar_and_lookup(tmp_path):
    cal = load(tmp_path, payload())
    assert isinstance(cal.sessions, tuple)
    assert cal.get(date(2026, 10, 23)).open == datetime.fromisoformat('2026-10-23T09:00:00+07:00')
    assert cal.get(date(2026, 10, 23)).close.hour == 15
    assert cal.next_session(date(2026, 10, 23)).date == date(2026, 10, 26)
    assert cal.next_session(date(2026, 10, 26)).date == date(2026, 10, 28)
    with pytest.raises(MissingSession):
        cal.get(date(2026, 10, 27))
    with pytest.raises(MissingSession):
        cal.next_session(date(2026, 10, 28))


@pytest.mark.parametrize('kind', ['duplicate', 'overlap', 'naive', 'reverse', 'wrongdate', 'wrongzone', 'offset', 'offgrid', 'source', 'empty'])
def test_invalid_calendar(tmp_path, kind):
    data = payload()
    row = data['sessions'][0]
    if kind == 'duplicate':
        data['sessions'].append(row)
    elif kind == 'overlap':
        row['intervals'][1][0] = '2026-10-26T11:00:00+07:00'
    elif kind == 'naive':
        row['intervals'][0][0] = '2026-10-26T09:00:00'
    elif kind == 'reverse':
        row['intervals'][0].reverse()
    elif kind == 'wrongdate':
        row['date'] = '2026-10-25'
    elif kind == 'wrongzone':
        data['timezone'] = 'UTC'
    elif kind == 'offset':
        row['intervals'][0][0] = '2026-10-26T09:00:00+00:00'
    elif kind == 'offgrid':
        row['intervals'][0][0] = '2026-10-26T09:01:00+07:00'
    elif kind == 'source':
        data.pop('source_url')
    else:
        row['intervals'] = []
    with pytest.raises(ValueError):
        load(tmp_path, data)
