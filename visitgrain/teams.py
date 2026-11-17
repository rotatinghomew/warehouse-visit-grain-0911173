"""团队级事实与显式覆盖声明。

团队材料保留自己的事实粒度：总人数是覆盖范围内的不同参与者，覆盖多馆不等于
每馆到齐。团队与匿名明细之间的包含关系只能由报送方显式声明，系统不猜测分配。
"""
from .materials import live, stations_of
from .storage import atomic, require_text

LIVE_COVERAGE = """
SELECT c.team_material,c.team_version,c.detail_material,c.detail_version,
       c.visit_id,v.person,v.station,v.day,v.school,v.stage
FROM coverage c
JOIN materials tm ON tm.name=c.team_material AND tm.version=c.team_version
                     AND tm.status='active'
JOIN materials dm ON dm.name=c.detail_material AND dm.version=c.detail_version
                     AND dm.status='active'
JOIN visits v ON v.visit_id=c.visit_id
WHERE c.status='active'
  AND EXISTS (SELECT 1 FROM origins o
              WHERE o.visit_id=c.visit_id AND o.status='active')
"""


def _covered_rows(database, team_name, team_version):
    return database.execute(
        f"""SELECT c.visit_id,v.person,v.station,v.school,v.day,v.stage
            FROM ({LIVE_COVERAGE}) c JOIN visits v ON v.visit_id=c.visit_id
            WHERE c.team_material=? AND c.team_version=?""",
        (team_name, team_version)).fetchall()


def _other_team_conflicts(database, team, school, day, stage, visit_ids):
    if not visit_ids:
        return []
    placeholders = ','.join('?' for _ in visit_ids)
    return database.execute(
        f"""SELECT DISTINCT c.team_material,c.visit_id FROM ({LIVE_COVERAGE}) c
            WHERE c.school=? AND c.day=? AND c.stage IS ?
              AND c.team_material!=? AND c.visit_id IN ({placeholders})""",
        (school, day, stage, team, *visit_ids)).fetchall()


def declare_coverage(database, team_material, detail_material, visit_ids):
    """声明团队材料由某个体材料中的这些到访明细细化覆盖。"""
    visit_ids = sorted(set(visit_ids))
    if not visit_ids:
        raise ValueError("覆盖声明需要至少一条到访明细")
    for visit_id in visit_ids:
        require_text(visit_id, '到访标识')
    with atomic(database):
        team = live(database, team_material)
        detail = live(database, detail_material)
        if not team:
            raise KeyError(team_material)
        if not detail:
            raise KeyError(detail_material)
        if team['kind'] != 'team':
            raise ValueError(f"材料{team_material}不是团队材料，不能登记覆盖声明")
        if detail['kind'] != 'individual':
            raise ValueError(f"材料{detail_material}不是个体明细材料")
        team_stations = stations_of(database, team_material, team['version'])
        rows = []
        for visit_id in visit_ids:
            origin = database.execute(
                """SELECT v.* FROM live_visits v
                   JOIN origins o ON o.visit_id=v.visit_id
                   JOIN materials m ON m.name=o.material AND m.version=o.version
                                      AND m.status='active'
                   WHERE v.visit_id=? AND o.material=? AND o.status='active'""",
                (visit_id, detail_material)).fetchone()
            if not origin:
                raise ValueError(
                    f"覆盖声明不成立：到访{visit_id}不是材料{detail_material}当前可查的明细")
            if (origin['school'], origin['day'], origin['stage']) != \
               (team['school'], team['day'], team['stage']):
                raise ValueError(
                    f"覆盖声明不成立：到访{visit_id}与团队材料{team_material}的"
                    "学校、日期或学段不一致")
            if origin['station'] not in team_stations:
                raise ValueError(
                    f"覆盖声明不成立：到访{visit_id}的场馆{origin['station']}"
                    f"不在团队材料{team_material}的声明范围")
            rows.append(origin)
        clashes = _other_team_conflicts(
            database, team_material, team['school'], team['day'], team['stage'], visit_ids)
        for clash in clashes:
            raise ValueError(
                f"覆盖声明冲突：到访{clash['visit_id']}已被团队材料"
                f"{clash['team_material']}声明覆盖，不能同时属于{team_material}")
        already = {
            row['visit_id'] for row in database.execute(
                'SELECT visit_id FROM coverage WHERE team_material=? AND team_version=? '
                'AND detail_material=? AND detail_version=? AND status=?',
                (team_material, team['version'], detail_material, detail['version'],
                 'active')).fetchall()}
        pending = [visit_id for visit_id in visit_ids if visit_id not in already]
        if not pending:
            return False
        covered_people = {
            row['person'] for row in _covered_rows(database, team_material, team['version'])}
        covered_people.update(row['person'] for row in rows)
        if len(covered_people) > team['team_headcount']:
            raise ValueError(
                f"覆盖声明冲突：团队材料{team_material}总人数{team['team_headcount']}"
                f"不足以覆盖{len(covered_people)}名不同参与者"
                f"（涉及材料{detail_material}）")
        for visit_id in pending:
            database.execute(
                """INSERT INTO coverage VALUES(?,?,?,?,?,'active')
                   ON CONFLICT(team_material,team_version,detail_material,detail_version,
                               visit_id)
                   DO UPDATE SET status='active'""",
                (team_material, team['version'], detail_material, detail['version'],
                 visit_id))
    return True


def retract_coverage(database, team_material, detail_material, visit_ids):
    """撤回覆盖声明；团队余量随之回升，明细本身不受影响。"""
    visit_ids = sorted(set(visit_ids))
    with atomic(database):
        cursor = database.execute(
            f"""UPDATE coverage SET status='withdrawn'
                WHERE status='active' AND team_material=? AND detail_material=?
                  AND visit_id IN ({','.join('?' for _ in visit_ids)})""",
            (team_material, detail_material, *visit_ids))
        if cursor.rowcount == 0:
            raise KeyError("没有匹配的生效覆盖声明")


def validate_team_change(database, current, school, day, stage, stations, headcount):
    rows = _covered_rows(database, current['name'], current['version'])
    if not rows:
        return
    covered_people = {row['person'] for row in rows}
    if headcount < len(covered_people):
        raise ValueError(
            f"团队材料{current['name']}更正冲突：新总人数{headcount}少于已声明覆盖的"
            f"{len(covered_people)}人（涉及材料"
            + '、'.join(sorted({r['detail_material'] for r in
                                database.execute(
                                    f'SELECT detail_material FROM ({LIVE_COVERAGE}) '
                                    'WHERE team_material=?', (current['name'],)).fetchall()}))
            + '）')
    for row in rows:
        if row['station'] not in stations:
            raise ValueError(
                f"团队材料{current['name']}更正冲突：已覆盖到访{row['visit_id']}的场馆"
                f"{row['station']}不在新声明范围")
        if (row['school'], row['day'], row['stage']) != (school, day, stage):
            raise ValueError(
                f"团队材料{current['name']}更正冲突：已覆盖到访{row['visit_id']}的"
                "学校、日期或学段不能随更正改变")


def carry_team_coverage(database, name, old_version, new_version):
    """团队材料更正后，把生效覆盖声明锚定到新版本。"""
    database.execute(
        """INSERT INTO coverage(team_material,team_version,detail_material,detail_version,
                                visit_id,status)
           SELECT team_material,?,detail_material,detail_version,visit_id,status
           FROM coverage WHERE team_material=? AND team_version=? AND status='active'""",
        (new_version, name, old_version))


def carry_detail_coverage(database, name, old_version, new_version):
    """个体材料更正后，把引用它的生效覆盖声明锚定到新版本。"""
    database.execute(
        """INSERT INTO coverage(team_material,team_version,detail_material,detail_version,
                                visit_id,status)
           SELECT team_material,team_version,detail_material,?,visit_id,status
           FROM coverage WHERE detail_material=? AND detail_version=? AND status='active'""",
        (new_version, name, old_version))


def conflicts(database):
    """防御性扫描：正常写入路径会拦截，这里仍把可能的双重团队覆盖点名列出。"""
    return [dict(row) for row in database.execute(
        f"""SELECT c1.team_material AS first_team,c2.team_material AS second_team,
                   c1.detail_material,c1.visit_id
            FROM ({LIVE_COVERAGE}) c1
            JOIN ({LIVE_COVERAGE}) c2
              ON c1.visit_id=c2.visit_id AND c1.team_material<c2.team_material
                 AND c1.school=c2.school AND c1.day=c2.day
            ORDER BY c1.visit_id,c1.team_material""")]
