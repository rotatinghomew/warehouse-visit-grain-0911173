import json

from .attendance import detail
from .materials import stations_of
from .storage import atomic, connect, records
from .teams import LIVE_COVERAGE, conflicts

DDL = """
CREATE TABLE IF NOT EXISTS materials(
    name TEXT,version INTEGER,school TEXT,day TEXT,stage TEXT,
    kind TEXT,team_headcount INTEGER,status TEXT,checksum TEXT,
    PRIMARY KEY(name,version));
CREATE TABLE IF NOT EXISTS stations(
    material TEXT,version INTEGER,station TEXT,
    PRIMARY KEY(material,version,station),
    FOREIGN KEY(material,version) REFERENCES materials(name,version));
CREATE TABLE IF NOT EXISTS visits(
    visit_id TEXT PRIMARY KEY,person TEXT,station TEXT,day TEXT,
    school TEXT,stage TEXT,checksum TEXT);
CREATE TABLE IF NOT EXISTS origins(
    visit_id TEXT,material TEXT,version INTEGER,status TEXT,
    PRIMARY KEY(visit_id,material,version),
    FOREIGN KEY(material,version) REFERENCES materials(name,version));
CREATE TABLE IF NOT EXISTS coverage(
    team_material TEXT,team_version INTEGER,detail_material TEXT,detail_version INTEGER,
    visit_id TEXT,status TEXT,
    PRIMARY KEY(team_material,team_version,detail_material,detail_version,visit_id));
CREATE TABLE IF NOT EXISTS extracts(name TEXT PRIMARY KEY,payload TEXT);
CREATE VIEW IF NOT EXISTS live_visits AS
SELECT v.* FROM visits v
WHERE EXISTS (SELECT 1 FROM origins o
              WHERE o.visit_id=v.visit_id AND o.status='active');
"""


class VisitWarehouse:
    def __init__(self, root):
        self.db = connect(root, DDL)

    def close(self):
        self.db.close()


_GRAINS = {'station': 'station', 'day': 'day', 'school': 'school', 'stage': 'stage'}


def cube(database, grain='station'):
    if grain == 'all':
        return records(database,
                       'SELECT COUNT(*) visits,COUNT(DISTINCT person) people FROM live_visits')
    if grain not in _GRAINS:
        raise ValueError("不支持的汇总粒度")
    field = _GRAINS[grain]
    return records(database, f"""
        SELECT {field},COUNT(*) visits,COUNT(DISTINCT person) people
        FROM live_visits GROUP BY {field} ORDER BY {field}""")


def _filters(criteria):
    clauses, parameters = [], []
    for field, value in criteria:
        if value is not None:
            clauses.append(f'{field}=?')
            parameters.append(value)
    return clauses, parameters


def summary(database, *, day=None, station=None, stage=None, school=None):
    """按日期、场馆、学段（及学校）查询，区分三段口径：

    addable_detail：当前可查的匿名明细，人数可在查询维度内直接相加；
    teams.covered_people：团队材料中已被明细细化的部分（同时出现在明细里，不重复相加）；
    teams.residual_people：团队总人数中尚未明细化、现有信息无法唯一分配的余量。
    多站团队的余量标记 residual_allocatable=false，不替报送方按站猜分配。
    """
    detail_clauses, detail_parameters = _filters(
        (('day', day), ('station', station), ('stage', stage), ('school', school)))
    detail_condition = ('WHERE ' + ' AND '.join(detail_clauses)) if detail_clauses else ''
    detail_rows = records(database, f"""
        SELECT station,day,school,stage,COUNT(*) visits,COUNT(DISTINCT person) people
        FROM live_visits {detail_condition}
        GROUP BY station,day,school,stage ORDER BY station,day,school,stage""",
        detail_parameters)

    teams = []
    for team in database.execute(
            "SELECT * FROM materials WHERE kind='team' AND status='active' ORDER BY name"):
        team_stations = stations_of(database, team['name'], team['version'])
        in_scope = (day is None or team['day'] == day) and \
                   (stage is None or team['stage'] == stage) and \
                   (school is None or team['school'] == school) and \
                   (station is None or station in team_stations)
        if not in_scope:
            continue
        coverage_clauses = ['c.team_material=?', 'c.team_version=?']
        coverage_parameters = [team['name'], team['version']]
        if day is not None:
            coverage_clauses.append('c.day=?')
            coverage_parameters.append(day)
        if stage is not None:
            coverage_clauses.append('c.stage=?')
            coverage_parameters.append(stage)
        if school is not None:
            coverage_clauses.append('c.school=?')
            coverage_parameters.append(school)
        if station is not None:
            coverage_clauses.append('v.station=?')
            coverage_parameters.append(station)
        covered = records(database, f"""
            SELECT DISTINCT c.visit_id,c.detail_material,v.person
            FROM ({LIVE_COVERAGE}) c JOIN visits v ON v.visit_id=c.visit_id
            WHERE {' AND '.join(coverage_clauses)}""", coverage_parameters)
        covered_people = {row['person'] for row in covered}
        covered_count = len(covered_people)
        teams.append({
            'team_material': team['name'],
            'school': team['school'],
            'day': team['day'],
            'stage': team['stage'],
            'stations': team_stations,
            'headcount': team['team_headcount'],
            'covered_people': covered_count,
            'residual_people': team['team_headcount'] - covered_count,
            'residual_allocatable': len(team_stations) == 1,
            'covered_visits': sorted(row['visit_id'] for row in covered),
            'detail_materials': sorted({row['detail_material'] for row in covered}),
        })
    return {
        'addable_detail': detail_rows,
        'teams': teams,
        'conflicts': conflicts(database),
    }


def extract(database, name):
    with atomic(database):
        payload = {
            'detail': detail(database),
            'stations': cube(database),
            'total': cube(database, 'all'),
            'coverage': summary(database),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        old = database.execute('SELECT payload FROM extracts WHERE name=?', (name,)).fetchone()
        if old and old[0] != encoded:
            raise ValueError("摘录名称已被使用")
        database.execute('INSERT OR IGNORE INTO extracts VALUES(?,?)', (name, encoded))
    return payload


def read_extract(database, name):
    row = database.execute('SELECT payload FROM extracts WHERE name=?', (name,)).fetchone()
    if not row:
        raise KeyError(name)
    return json.loads(row[0])
