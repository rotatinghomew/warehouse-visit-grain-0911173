from .materials import active_version, contains, live
from .storage import atomic, fingerprint, records, require_text


def load(database, material, visits):
    """把匿名个体到访明细接入材料的当前生效版本。"""
    with atomic(database):
        document = live(database, material)
        if not document:
            raise KeyError(material)
        if document['kind'] != 'individual':
            raise ValueError(f"材料{material}是团队材料，不接受个体到访明细")
        version = document['version']
        inserted = 0
        for visit in visits:
            require_text(visit['visit_id'], '到访标识')
            require_text(visit['person'], '匿名参与者')
            if not contains(database, material, visit['station']):
                raise ValueError("到访场馆不在材料声明中")
            checksum = fingerprint([visit['person'], visit['station'], document['day'],
                                    document['school'], document['stage']])
            old = database.execute(
                'SELECT checksum FROM visits WHERE visit_id=?', (visit['visit_id'],)).fetchone()
            if old:
                if old[0] != checksum:
                    raise ValueError("到访标识冲突")
                database.execute(
                    "INSERT INTO origins VALUES(?,?,?,'active') "
                    "ON CONFLICT(visit_id,material,version) DO UPDATE SET status='active'",
                    (visit['visit_id'], material, version))
                continue
            database.execute(
                'INSERT INTO visits VALUES(?,?,?,?,?,?,?)',
                (visit['visit_id'], visit['person'], visit['station'], document['day'],
                 document['school'], document['stage'], checksum))
            database.execute(
                'INSERT INTO origins VALUES(?,?,?,?)',
                (visit['visit_id'], material, version, 'active'))
            inserted += 1
    return inserted


def withdraw_visit(database, material, visit_id):
    """从指定材料中收回一条到访来源；没有其他生效材料时该到访不再可查。"""
    with atomic(database):
        version = active_version(database, material)
        if version is None:
            raise KeyError(material)
        cursor = database.execute(
            "UPDATE origins SET status='withdrawn' "
            "WHERE visit_id=? AND material=? AND version=? AND status='active'",
            (visit_id, material, version))
        if cursor.rowcount == 0:
            raise KeyError(visit_id)
        # 同一材料若曾以旧版本登记，也一并失效，避免历史版本重新“供出”这条明细
        database.execute(
            "UPDATE origins SET status='withdrawn' WHERE visit_id=? AND material=?",
            (visit_id, material))


def detail(database):
    return records(database, """
        SELECT v.visit_id,v.person,v.station,v.day,v.school,v.stage
        FROM visits v
        WHERE EXISTS (SELECT 1 FROM origins o
                      WHERE o.visit_id=v.visit_id AND o.status='active')
        ORDER BY v.visit_id""")
