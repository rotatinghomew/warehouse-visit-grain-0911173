import tempfile
import unittest


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.directory=self.temporary.name
        self.resources=[]

    def open(self, factory):
        resource=factory(self.directory)
        self.resources.append(resource)
        return resource

    def tearDown(self):
        for resource in reversed(self.resources):
            resource.close()
        self.temporary.cleanup()

from visitgrain.cubes import VisitWarehouse, cube, extract, read_extract
from visitgrain.materials import submit
from visitgrain.attendance import load, detail


class Behavior(WorkspaceTest):
    def test_material_range_and_replay(self):
        warehouse = self.open(VisitWarehouse)
        self.assertTrue(submit(warehouse.db,'M1','S1',['A','B'],'2026-03-01'))
        self.assertFalse(submit(warehouse.db,'M1','S1',['B','A'],'2026-03-01'))
        with self.assertRaises(ValueError):
            submit(warehouse.db,'M1','S1',['C'],'2026-03-01')
        with self.assertRaises(ValueError):
            load(warehouse.db,'M1',[{'visit_id':'V1','person':'P1','station':'C'}])

    def test_individual_grains(self):
        warehouse = self.open(VisitWarehouse)
        submit(warehouse.db,'M1','S1',['A','B'],'2026-03-01')
        self.assertEqual(load(warehouse.db,'M1',[{'visit_id':'V1','person':'P1','station':'A'},{'visit_id':'V2','person':'P1','station':'B'}]),2)
        self.assertEqual(cube(warehouse.db,'all'),[{'visits':2,'people':1}])
        self.assertEqual(sum(row['people'] for row in cube(warehouse.db)),2)
        with self.assertRaises(ValueError):
            cube(warehouse.db,'arbitrary')

    def test_visit_conflict_rolls_back(self):
        warehouse = self.open(VisitWarehouse)
        submit(warehouse.db,'M1','S1',['A'],'2026-03-01')
        row={'visit_id':'V1','person':'P1','station':'A'}
        load(warehouse.db,'M1',[row])
        self.assertEqual(load(warehouse.db,'M1',[row]),0)
        with self.assertRaises(ValueError):
            load(warehouse.db,'M1',[dict(row,visit_id='V2'),dict(row,person='P2')])
        self.assertEqual(len(detail(warehouse.db)),1)

    def test_extract_is_immutable(self):
        warehouse = self.open(VisitWarehouse)
        submit(warehouse.db,'M1','S1',['A'],'2026-03-01')
        load(warehouse.db,'M1',[{'visit_id':'V1','person':'P1','station':'A'}])
        old=extract(warehouse.db,'三月')
        load(warehouse.db,'M1',[{'visit_id':'V2','person':'P2','station':'A'}])
        self.assertEqual(read_extract(warehouse.db,'三月'),old)
        reopened=self.open(VisitWarehouse)
        self.assertEqual(cube(reopened.db,'all')[0]['people'],2)
