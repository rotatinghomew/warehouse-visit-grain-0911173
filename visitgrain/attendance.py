from .materials import contains
from .storage import atomic, fingerprint, require_text, records


def load(database, material, visits):
    with atomic(database):
        document = database.execute('SELECT * FROM materials WHERE name=?', (material,)).fetchone()
        if not document:
            raise KeyError(material)
        inserted = 0
        for visit in visits:
            require_text(visit['visit_id'], '到访标识')
            require_text(visit['person'], '匿名参与者')
            if not contains(database,material,visit['station']):
                raise ValueError("到访场馆不在材料声明中")
            checksum = fingerprint([visit['person'],visit['station'],document['day'],document['school']])
            old = database.execute('SELECT checksum FROM visits WHERE visit_id=?', (visit['visit_id'],)).fetchone()
            if old:
                if old[0] != checksum:
                    raise ValueError("到访标识冲突")
                database.execute('INSERT OR IGNORE INTO origins VALUES(?,?)', (visit['visit_id'],material))
                continue
            database.execute('INSERT INTO visits VALUES(?,?,?,?,?,?)', (visit['visit_id'],visit['person'],visit['station'],document['day'],document['school'],checksum))
            database.execute('INSERT INTO origins VALUES(?,?)', (visit['visit_id'],material))
            inserted += 1
    return inserted


def detail(database):
    return records(database, 'SELECT visit_id,person,station,day,school FROM visits ORDER BY visit_id')
