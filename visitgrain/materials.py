from .storage import atomic, fingerprint, require_text


def submit(database, name, school, stations, day):
    from datetime import date
    date.fromisoformat(day)
    require_text(school, '学校')
    stations = sorted(set(stations))
    if not stations or any(not isinstance(item,str) or not item for item in stations):
        raise ValueError("材料需包含有效场馆")
    checksum = fingerprint([school,stations,day])
    with atomic(database):
        old = database.execute('SELECT checksum FROM materials WHERE name=?', (name,)).fetchone()
        if old:
            if old[0] != checksum:
                raise ValueError("材料内容冲突")
            return False
        database.execute('INSERT INTO materials VALUES(?,?,?,?)', (name,school,day,checksum))
        database.executemany('INSERT INTO stations VALUES(?,?)', [(name,station) for station in stations])
    return True


def contains(database, material, station):
    return bool(database.execute('SELECT 1 FROM stations WHERE material=? AND station=?', (material,station)).fetchone())
