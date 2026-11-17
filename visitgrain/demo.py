from .cubes import VisitWarehouse, cube, extract, summary
from .materials import correct, submit
from .attendance import load, withdraw_visit
from .teams import declare_coverage


def run(root):
    warehouse = VisitWarehouse(root)
    try:
        # 只交明细的学校，报送方式与以前完全一致（学段字段可选）
        submit(warehouse.db, '材料A', 'S1', ['A馆', 'B馆'], '2026-03-01', stage='初中')
        load(warehouse.db, '材料A', [
            {'visit_id': 'V1', 'person': 'P1', 'station': 'A馆'},
            {'visit_id': 'V2', 'person': 'P1', 'station': 'B馆'},
            {'visit_id': 'V3', 'person': 'P2', 'station': 'A馆'}])

        # 只能先交团队总人数的学校：一份材料覆盖两站，不拆成每站各一组人
        submit(warehouse.db, '团队T', 'S2', ['A馆', 'C馆'], '2026-03-01',
               stage='小学', kind='team', headcount=40)

        # 后来补出其中一部分明细，并显式声明它细化覆盖了该团队的一部分人
        submit(warehouse.db, '材料B', 'S2', ['A馆'], '2026-03-01', stage='小学')
        load(warehouse.db, '材料B', [
            {'visit_id': 'V4', 'person': 'P3', 'station': 'A馆'},
            {'visit_id': 'V5', 'person': 'P4', 'station': 'A馆'}])
        declare_coverage(warehouse.db, '团队T', '材料B', ['V4', 'V5'])

        first = extract(warehouse.db, '三月摘录')

        # 团队更正：人数从 40 调整为 38；摘录已固化，不受影响
        correct(warehouse.db, '团队T', 'S2', ['A馆', 'C馆'], '2026-03-01',
                stage='小学', headcount=38)

        # 明细被收回：可查明细与团队覆盖/余量同步变化
        withdraw_visit(warehouse.db, '材料B', 'V5')

        return {
            'first_extract': first,
            'live_summary': summary(warehouse.db, day='2026-03-01'),
        }
    finally:
        warehouse.close()
