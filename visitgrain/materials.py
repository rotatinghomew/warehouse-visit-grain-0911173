from datetime import date

from .storage import atomic, fingerprint, require_text

KINDS = ('individual', 'team')


def _normalize(school, stations, day, stage, kind, headcount):
    require_text(school, '学校')
    date.fromisoformat(day)
    stations = sorted(set(stations))
    if not stations or any(not isinstance(item, str) or not item for item in stations):
        raise ValueError("材料需包含有效场馆")
    if kind not in KINDS:
        raise ValueError("材料粒度只能是个体材料或团队材料")
    if stage is not None:
        require_text(stage, '学段')
    if kind == 'team':
        if not isinstance(headcount, int) or isinstance(headcount, bool) or headcount < 1:
            raise ValueError("团队材料需要正整数总人数")
    elif headcount is not None:
        raise ValueError("个体材料不登记团队总人数")
    else:
        headcount = None
    return stations, headcount


def _insert(database, name, version, school, day, stage, kind, headcount, status, checksum, stations):
    database.execute(
        'INSERT INTO materials VALUES(?,?,?,?,?,?,?,?,?)',
        (name, version, school, day, stage, kind, headcount, status, checksum))
    database.executemany(
        'INSERT INTO stations VALUES(?,?,?)',
        [(name, version, station) for station in stations])


def submit(database, name, school, stations, day, *, stage=None, kind='individual', headcount=None):
    """登记一份新材料。默认个体材料，现有只交明细的单位调用方式不变。"""
    stations, headcount = _normalize(school, stations, day, stage, kind, headcount)
    checksum = fingerprint([school, stations, day, stage, kind, headcount])
    with atomic(database):
        latest = database.execute(
            'SELECT version,status,checksum FROM materials WHERE name=? ORDER BY version DESC LIMIT 1',
            (name,)).fetchone()
        if latest:
            if latest['checksum'] == checksum and latest['status'] == 'active':
                return False
            if latest['status'] == 'active':
                raise ValueError("材料已有生效版本，内容变更请使用 correct")
        base = latest['version'] if latest else 0
        _insert(database, name, base + 1, school, day, stage, kind, headcount,
                'active', checksum, stations)
    return True


def correct(database, name, school, stations, day, *, stage=None, kind=None, headcount=None):
    """更正材料：追加一个生效版本，原版本标记为 superseded 并保留。"""
    with atomic(database):
        current = live(database, name)
        if not current:
            raise KeyError(name)
        kind = current['kind'] if kind is None else kind
        stations, headcount = _normalize(school, stations, day, stage, kind, headcount)
        checksum = fingerprint([school, stations, day, stage, kind, headcount])
        if checksum == current['checksum']:
            return False
        if kind == 'team':
            from .teams import validate_team_change
            validate_team_change(database, current, school, day, stage, stations, headcount)
        else:
            _validate_individual_change(database, current, school, day, stage, stations)
        new_version = current['version'] + 1
        database.execute(
            "UPDATE materials SET status='superseded' WHERE name=? AND version=?",
            (name, current['version']))
        _insert(database, name, new_version, school, day, stage, kind, headcount,
                'active', checksum, stations)
        if kind == 'team':
            from .teams import carry_team_coverage
            carry_team_coverage(database, name, current['version'], new_version)
        else:
            _carry_origins(database, name, current['version'], new_version)
            from .teams import carry_detail_coverage
            carry_detail_coverage(database, name, current['version'], new_version)
    return True


def _validate_individual_change(database, current, school, day, stage, stations):
    rows = database.execute(
        """SELECT v.visit_id,v.station FROM origins o
           JOIN visits v ON v.visit_id=o.visit_id
           WHERE o.material=? AND o.version=? AND o.status='active'""",
        (current['name'], current['version'])).fetchall()
    for row in rows:
        if row['station'] not in stations:
            raise ValueError(
                f"材料{current['name']}更正冲突：到访{row['visit_id']}场馆"
                f"{row['station']}不在新声明范围")
    if school != current['school'] or day != current['day'] or stage != current['stage']:
        for row in rows:
            raise ValueError(
                f"材料{current['name']}更正冲突：到访{row['visit_id']}的学校、日期或学段"
                "不能随材料更正而改变")


def _carry_origins(database, name, old_version, new_version):
    database.execute(
        """INSERT OR IGNORE INTO origins(visit_id,material,version,status)
           SELECT visit_id,material,?,status FROM origins
           WHERE material=? AND version=? AND status='active'""",
        (new_version, name, old_version))


def withdraw(database, name):
    """收回材料的当前生效版本；其来源与覆盖声明随之失效，历史版本仍保留。"""
    with atomic(database):
        current = live(database, name)
        if not current:
            return False
        database.execute(
            "UPDATE materials SET status='withdrawn' WHERE name=? AND version=?",
            (name, current['version']))
        database.execute(
            "UPDATE origins SET status='withdrawn' WHERE material=? AND version=?",
            (name, current['version']))
    return True


def live(database, name):
    row = database.execute(
        'SELECT * FROM materials WHERE name=? ORDER BY version DESC LIMIT 1',
        (name,)).fetchone()
    return row if row and row['status'] == 'active' else None


def active_version(database, name):
    row = live(database, name)
    return row['version'] if row else None


def versions(database, name):
    from .storage import records
    return records(database,
                   'SELECT name,version,school,day,stage,kind,team_headcount,status,checksum '
                   'FROM materials WHERE name=? ORDER BY version', (name,))


def stations_of(database, name, version):
    return [row['station'] for row in database.execute(
        'SELECT station FROM stations WHERE material=? AND version=? ORDER BY station',
        (name, version)).fetchall()]


def contains(database, material, station):
    current = live(database, material)
    if not current:
        return False
    return bool(database.execute(
        'SELECT 1 FROM stations WHERE material=? AND version=? AND station=?',
        (material, current['version'], station)).fetchone())
