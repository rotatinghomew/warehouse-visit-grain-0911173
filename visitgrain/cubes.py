import json

from .attendance import detail
from .storage import atomic, connect, records

DDL = """
CREATE TABLE IF NOT EXISTS materials(name TEXT PRIMARY KEY,school TEXT,day TEXT,checksum TEXT);
CREATE TABLE IF NOT EXISTS stations(material TEXT REFERENCES materials(name),station TEXT,PRIMARY KEY(material,station));
CREATE TABLE IF NOT EXISTS visits(visit_id TEXT PRIMARY KEY,person TEXT,station TEXT,day TEXT,school TEXT,checksum TEXT);
CREATE TABLE IF NOT EXISTS origins(visit_id TEXT REFERENCES visits(visit_id),material TEXT REFERENCES materials(name),PRIMARY KEY(visit_id,material));
CREATE TABLE IF NOT EXISTS extracts(name TEXT PRIMARY KEY,payload TEXT);
"""


class VisitWarehouse:
    def __init__(self, root):
        self.db = connect(root, DDL)

    def close(self):
        self.db.close()


def cube(database, grain='station'):
    if grain == 'all':
        return records(database, 'SELECT COUNT(*) visits,COUNT(DISTINCT person) people FROM visits')
    fields = {'station':'station','day':'day','school':'school'}
    if grain not in fields:
        raise ValueError("不支持的汇总粒度")
    field = fields[grain]
    return records(database, f'SELECT {field},COUNT(*) visits,COUNT(DISTINCT person) people FROM visits GROUP BY {field} ORDER BY {field}')


def extract(database, name):
    with atomic(database):
        payload = {'detail':detail(database),'stations':cube(database),'total':cube(database,'all')}
        encoded = json.dumps(payload,ensure_ascii=False,sort_keys=True)
        old = database.execute('SELECT payload FROM extracts WHERE name=?',(name,)).fetchone()
        if old and old[0] != encoded:
            raise ValueError("摘录名称已被使用")
        database.execute('INSERT OR IGNORE INTO extracts VALUES(?,?)',(name,encoded))
    return payload


def read_extract(database,name):
    row = database.execute('SELECT payload FROM extracts WHERE name=?',(name,)).fetchone()
    if not row:
        raise KeyError(name)
    return json.loads(row[0])
