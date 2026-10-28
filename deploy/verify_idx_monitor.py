"""Read-only operator verification. Does not send messages or expose chat IDs."""
import json
import sqlite3
from pathlib import Path


def describe(path):
    if not Path(path).exists():
        return {'exists': False}
    connection = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {'exists': True, 'tables': {name: connection.execute('SELECT count(*) FROM "' + name.replace('"','""') + '"').fetchone()[0] for name in tables if not name.startswith('sqlite_')}}
    finally:
        connection.close()


if __name__ == '__main__':
    print(json.dumps(describe('/root/projects/idx-stockbit-monitor.sqlite')))
