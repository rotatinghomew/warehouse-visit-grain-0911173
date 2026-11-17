from .cubes import VisitWarehouse, cube, extract
from .materials import submit
from .attendance import load


def run(root):
    warehouse=VisitWarehouse(root)
    try:
        submit(warehouse.db,'材料A','S1',['A馆','B馆'],'2026-03-01')
        load(warehouse.db,'材料A',[
            {'visit_id':'V1','person':'P1','station':'A馆'},
            {'visit_id':'V2','person':'P1','station':'B馆'},
            {'visit_id':'V3','person':'P2','station':'A馆'}])
        return extract(warehouse.db,'月度摘录')
    finally:
        warehouse.close()
