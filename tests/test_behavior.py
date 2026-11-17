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

from visitgrain.cubes import VisitWarehouse, cube, extract, read_extract, summary
from visitgrain.materials import submit, correct, withdraw, versions, live
from visitgrain.attendance import load, detail, withdraw_visit
from visitgrain.teams import declare_coverage, retract_coverage, conflicts


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


def _seed(warehouse):
    # S2 小学：团队 40 人覆盖 A/C 两站，后补 2 条 A 馆明细并显式声明覆盖
    submit(warehouse.db, 'T1', 'S2', ['A馆', 'C馆'], '2026-03-01',
           stage='小学', kind='team', headcount=40)
    submit(warehouse.db, 'D1', 'S2', ['A馆'], '2026-03-01', stage='小学')
    load(warehouse.db, 'D1', [
        {'visit_id': 'V4', 'person': 'P3', 'station': 'A馆'},
        {'visit_id': 'V5', 'person': 'P4', 'station': 'A馆'}])
    declare_coverage(warehouse.db, 'T1', 'D1', ['V4', 'V5'])


class TeamMaterial(WorkspaceTest):
    def test_team_keeps_own_grain_and_three_way_split(self):
        warehouse = self.open(VisitWarehouse)
        _seed(warehouse)
        report = summary(warehouse.db, day='2026-03-01')
        team = next(row for row in report['teams'] if row['team_material'] == 'T1')
        self.assertEqual(team['headcount'], 40)
        self.assertEqual(team['covered_people'], 2)
        self.assertEqual(team['residual_people'], 38)
        # 多站团队的余量不可按单站分配
        self.assertFalse(team['residual_allocatable'])
        self.assertEqual(team['stations'], ['A馆', 'C馆'])
        # 明细仍可直接相加，团队总人数没有被拆进任何一站的 cube
        station_rows = {row['station']: row for row in cube(warehouse.db)}
        self.assertEqual(station_rows['A馆']['people'], 2)
        self.assertNotIn('C馆', station_rows)

    def test_single_station_residual_is_allocatable(self):
        warehouse = self.open(VisitWarehouse)
        submit(warehouse.db, 'T2', 'S3', ['A馆'], '2026-03-01',
               stage='初中', kind='team', headcount=10)
        report = summary(warehouse.db, station='A馆')
        team = report['teams'][0]
        self.assertTrue(team['residual_allocatable'])
        self.assertEqual(team['residual_people'], 10)

    def test_stage_and_station_filters(self):
        warehouse = self.open(VisitWarehouse)
        _seed(warehouse)
        primary = summary(warehouse.db, stage='小学')
        self.assertEqual([t['team_material'] for t in primary['teams']], ['T1'])
        self.assertEqual(summary(warehouse.db, stage='初中')['teams'], [])
        at_c = summary(warehouse.db, station='C馆')
        # 余量在 C 馆维度可见但仍不可分配，且不带出 A 馆的已覆盖明细行
        self.assertEqual(len(at_c['teams']), 1)
        self.assertEqual(at_c['teams'][0]['covered_people'], 0)
        self.assertEqual(at_c['addable_detail'], [])

    def test_coverage_must_be_explicit_and_in_scope(self):
        warehouse = self.open(VisitWarehouse)
        submit(warehouse.db, 'T1', 'S2', ['A馆'], '2026-03-01',
               stage='小学', kind='team', headcount=5)
        submit(warehouse.db, 'D1', 'S2', ['B馆'], '2026-03-01', stage='小学')
        load(warehouse.db, 'D1', [{'visit_id': 'V9', 'person': 'P9', 'station': 'B馆'}])
        # 场馆不在团队声明范围
        with self.assertRaises(ValueError) as context:
            declare_coverage(warehouse.db, 'T1', 'D1', ['V9'])
        self.assertIn('T1', str(context.exception))
        self.assertIn('V9', str(context.exception))
        # 未声明覆盖前，团队余量不被任何明细抵减
        self.assertEqual(summary(warehouse.db)['teams'][0]['covered_people'], 0)
        # 学段不一致也不能建立覆盖
        submit(warehouse.db, 'T3', 'S2', ['B馆'], '2026-03-01',
               stage='初中', kind='team', headcount=5)
        with self.assertRaises(ValueError):
            declare_coverage(warehouse.db, 'T3', 'D1', ['V9'])

    def test_headcount_cannot_be_over_covered(self):
        warehouse = self.open(VisitWarehouse)
        submit(warehouse.db, 'T1', 'S2', ['A馆'], '2026-03-01',
               stage='小学', kind='team', headcount=1)
        submit(warehouse.db, 'D1', 'S2', ['A馆'], '2026-03-01', stage='小学')
        load(warehouse.db, 'D1', [
            {'visit_id': 'V4', 'person': 'P3', 'station': 'A馆'},
            {'visit_id': 'V5', 'person': 'P4', 'station': 'A馆'}])
        with self.assertRaises(ValueError) as context:
            declare_coverage(warehouse.db, 'T1', 'D1', ['V4', 'V5'])
        message = str(context.exception)
        self.assertIn('T1', message)
        self.assertIn('D1', message)
        # 冲突事务整体回滚，一条都没有登记
        self.assertEqual(summary(warehouse.db)['teams'][0]['covered_people'], 0)

    def test_same_anonymous_visit_cannot_cover_two_teams(self):
        warehouse = self.open(VisitWarehouse)
        submit(warehouse.db, 'T1', 'S2', ['A馆'], '2026-03-01',
               stage='小学', kind='team', headcount=10)
        submit(warehouse.db, 'T2', 'S2', ['A馆'], '2026-03-01',
               stage='小学', kind='team', headcount=10)
        submit(warehouse.db, 'D1', 'S2', ['A馆'], '2026-03-01', stage='小学')
        load(warehouse.db, 'D1', [{'visit_id': 'V4', 'person': 'P3', 'station': 'A馆'}])
        self.assertTrue(declare_coverage(warehouse.db, 'T1', 'D1', ['V4']))
        with self.assertRaises(ValueError) as context:
            declare_coverage(warehouse.db, 'T2', 'D1', ['V4'])
        self.assertIn('T1', str(context.exception))
        self.assertIn('T2', str(context.exception))

    def test_team_correction_versions_and_carries_coverage(self):
        warehouse = self.open(VisitWarehouse)
        _seed(warehouse)
        self.assertTrue(correct(warehouse.db, 'T1', 'S2', ['A馆', 'C馆'],
                                '2026-03-01', stage='小学', headcount=38))
        # 再次相同内容是幂等的
        self.assertFalse(correct(warehouse.db, 'T1', 'S2', ['A馆', 'C馆'],
                                 '2026-03-01', stage='小学', headcount=38))
        team = summary(warehouse.db)['teams'][0]
        self.assertEqual(team['headcount'], 38)
        self.assertEqual(team['covered_people'], 2)
        self.assertEqual(team['residual_people'], 36)
        self.assertEqual(versions(warehouse.db, 'T1')[0]['status'], 'superseded')
        self.assertEqual(live(warehouse.db, 'T1')['version'], 2)
        # 更正到小于已覆盖人数必须被点名拒绝
        with self.assertRaises(ValueError) as context:
            correct(warehouse.db, 'T1', 'S2', ['A馆', 'C馆'],
                    '2026-03-01', stage='小学', headcount=1)
        self.assertIn('D1', str(context.exception))
        self.assertEqual(live(warehouse.db, 'T1')['team_headcount'], 38)

    def test_individual_correction_rejects_lost_visits(self):
        warehouse = self.open(VisitWarehouse)
        _seed(warehouse)
        # 缩小场馆范围会丢掉已接入的到访，拒绝并点名
        with self.assertRaises(ValueError) as context:
            correct(warehouse.db, 'D1', 'S2', ['B馆'], '2026-03-01', stage='小学')
        self.assertIn('D1', str(context.exception))
        # 扩大场馆范围是合法更正，覆盖声明锚定到新版本仍然成立
        self.assertTrue(correct(warehouse.db, 'D1', 'S2', ['A馆', 'B馆'],
                                '2026-03-01', stage='小学'))
        self.assertEqual(summary(warehouse.db)['teams'][0]['covered_people'], 2)

    def test_withdraw_visit_updates_detail_and_residual(self):
        warehouse = self.open(VisitWarehouse)
        _seed(warehouse)
        withdraw_visit(warehouse.db, 'D1', 'V5')
        self.assertEqual({row['visit_id'] for row in detail(warehouse.db)}, {'V4'})
        team = summary(warehouse.db)['teams'][0]
        self.assertEqual(team['covered_people'], 1)
        self.assertEqual(team['residual_people'], 39)
        self.assertEqual(team['covered_visits'], ['V4'])
        # 重新补报同一到访后可恢复
        load(warehouse.db, 'D1', [{'visit_id': 'V5', 'person': 'P4', 'station': 'A馆'}])
        declare_coverage(warehouse.db, 'T1', 'D1', ['V5'])
        self.assertEqual(summary(warehouse.db)['teams'][0]['covered_people'], 2)

    def test_withdraw_material_and_coverage_retraction(self):
        warehouse = self.open(VisitWarehouse)
        _seed(warehouse)
        retract_coverage(warehouse.db, 'T1', 'D1', ['V4'])
        team = summary(warehouse.db)['teams'][0]
        self.assertEqual(team['covered_people'], 1)
        self.assertEqual(team['residual_people'], 39)
        # 明细本身不受覆盖撤回影响
        self.assertEqual(len(detail(warehouse.db)), 2)
        # 撤回后可重新声明同一条覆盖，且重复声明幂等
        self.assertTrue(declare_coverage(warehouse.db, 'T1', 'D1', ['V4']))
        self.assertFalse(declare_coverage(warehouse.db, 'T1', 'D1', ['V4']))
        self.assertEqual(summary(warehouse.db)['teams'][0]['covered_people'], 2)
        retract_coverage(warehouse.db, 'T1', 'D1', ['V4'])
        # 收回整份明细材料：可查性与团队覆盖同时变化
        self.assertTrue(withdraw(warehouse.db, 'D1'))
        self.assertEqual(detail(warehouse.db), [])
        team = summary(warehouse.db)['teams'][0]
        self.assertEqual(team['covered_people'], 0)
        self.assertEqual(team['residual_people'], 40)
        # 收回后可用同名新材料重新报送
        self.assertTrue(submit(warehouse.db, 'D1', 'S2', ['A馆'],
                               '2026-03-01', stage='小学'))

    def test_extract_reproduces_after_later_changes(self):
        warehouse = self.open(VisitWarehouse)
        _seed(warehouse)
        snapshot = extract(warehouse.db, '三月')
        correct(warehouse.db, 'T1', 'S2', ['A馆', 'C馆'],
                '2026-03-01', stage='小学', headcount=38)
        withdraw_visit(warehouse.db, 'D1', 'V5')
        self.assertEqual(read_extract(warehouse.db, '三月'), snapshot)
        frozen_team = snapshot['coverage']['teams'][0]
        self.assertEqual((frozen_team['headcount'], frozen_team['covered_people'],
                          frozen_team['residual_people']), (40, 2, 38))

    def test_duplicate_visit_across_individual_materials_is_shared_not_doubled(self):
        warehouse = self.open(VisitWarehouse)
        submit(warehouse.db, 'D1', 'S2', ['A馆'], '2026-03-01', stage='小学')
        submit(warehouse.db, 'D2', 'S2', ['A馆'], '2026-03-01', stage='小学')
        row = {'visit_id': 'V4', 'person': 'P3', 'station': 'A馆'}
        self.assertEqual(load(warehouse.db, 'D1', [row]), 1)
        self.assertEqual(load(warehouse.db, 'D2', [row]), 0)
        self.assertEqual(cube(warehouse.db, 'all'), [{'visits': 1, 'people': 1}])
        # 收回其中一个来源，另一个来源仍保证到访可查
        withdraw_visit(warehouse.db, 'D1', 'V4')
        self.assertEqual(cube(warehouse.db, 'all'), [{'visits': 1, 'people': 1}])

    def test_conflicts_are_named_not_hidden_in_total(self):
        warehouse = self.open(VisitWarehouse)
        _seed(warehouse)
        self.assertEqual(conflicts(warehouse.db), [])
        with self.assertRaises(ValueError):
            submit(warehouse.db, 'T1', 'S2', ['A馆'], '2026-03-01',
                   stage='小学', kind='team', headcount=5)
        with self.assertRaises(ValueError):
            submit(warehouse.db, 'T1', 'S9', ['A馆', 'C馆'], '2026-03-02',
                   stage='高中', kind='team', headcount=40)

