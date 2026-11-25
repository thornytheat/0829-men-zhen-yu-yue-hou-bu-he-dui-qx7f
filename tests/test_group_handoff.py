import pytest

from app.business import DomainIssue
from app.handoff import build_handoff
from app.intake.service import inspect
from app.review.service import execute, present_run, review_group


HEADER = ['record', 'case', 'kind', 'slot', 'attendee', 'minute', 'priority', 'expires', 'note']


def csv_bytes(rows):
    import csv
    import io
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(HEADER)
    writer.writerows(rows)
    return stream.getvalue().encode()


def audit(record, group, minute=1, priority='0'):
    return [record, group, 'audit', '0', '0', str(minute), str(priority), '0', '交班核对']


def initial(record, group, slot, attendee):
    return [record, group, 'initial', str(slot), str(attendee), '0', '0', '0', '初始号源']


def test_cross_group_conflict_holds_all_involved_groups_but_other_group_signs(store):
    data = csv_bytes([
        ['X1', 'G1', 'audit', '0', '0', '1', '0', '0', '冲突内容一'],
        ['X1', 'G2', 'audit', '0', '0', '2', '0', '0', '冲突内容二'],
        audit('OK1', 'OK'),
    ])
    report = execute(store, data)
    conclusions = report['handoff']['conclusions']
    assert conclusions['G1'] == 'HELD'
    assert conclusions['G2'] == 'HELD'
    assert conclusions['OK'] == 'READY'
    assert 'CROSS_GROUP_CONFLICT' in report['handoff']['groups'][0]['reasons']

    approved = review_group(store, report['id'], 'OK',
                            {'revision': 0, 'status': 'APPROVED', 'note': '其余组已对账'})
    assert approved['status'] == 'APPROVED'
    with pytest.raises(DomainIssue, match='UNRESOLVED_ISSUES'):
        review_group(store, report['id'], 'G1',
                     {'revision': 0, 'status': 'APPROVED', 'note': '试图签发涉事组'})


def test_unrecognizable_bad_row_holds_every_unsigned_group(store):
    data = csv_bytes([
        audit('OK1', 'OK'),
        ['BAD1', 'bad group!', 'initial', '0', '0', '0', '0', '0', '分组字段非法'],
    ])
    intake = inspect(data)
    handoff = build_handoff(intake, [])
    assert handoff['global_hold'] is True
    ok = next(item for item in handoff['groups'] if item['group'] == 'OK')
    assert ok['status'] == 'HELD' and ok['releasable'] is False


def test_moved_record_recomputes_groups_and_preserves_certificate(store):
    old = csv_bytes([
        initial('R1', 'A', 1, 101),
        audit('A1', 'A', 10, '1'),
        initial('R2', 'B', 2, 202),
        audit('B1', 'B', 10, '1'),
    ])
    old_run = execute(store, old)
    review_group(store, old_run['id'], 'A',
                 {'revision': 0, 'status': 'APPROVED', 'note': 'A 组核对完成'})
    review_group(store, old_run['id'], 'B',
                 {'revision': 0, 'status': 'APPROVED', 'note': 'B 组核对完成'})
    certificate_id = store.get_group_review('default', 'A')['certificate_id']
    assert certificate_id

    new = csv_bytes([
        initial('R1', 'B', 1, 101),
        audit('A1', 'A', 10, '1'),
        initial('R2', 'B', 2, 202),
        audit('B1', 'B', 10, '1'),
    ])
    new_run = execute(store, new)
    conclusions = new_run['handoff']['conclusions']
    assert conclusions['A'] == 'PENDING_REVIEW'
    assert conclusions['B'] == 'PENDING_REVIEW'
    assert any(move['record'] == 'R1' and move['old_group'] == 'A' and move['new_group'] == 'B'
               for move in new_run['handoff']['moved_records'])
    certificate = store.load_certificate(certificate_id)
    assert certificate['artifact']['group'] == 'A'
    assert store.load(old_run['id'])['id'] == old_run['id']
    assert store.load(old_run['id'])['group_reviews']['A']['status'] == 'APPROVED'
    old_view = present_run(store, old_run['id'])
    assert old_view['handoff']['conclusions']['A'] == 'APPROVED'


def test_unrecognizable_new_bad_row_only_holds_unsigned_groups(store):
    old = csv_bytes([audit('A1', 'A')])
    old_run = execute(store, old)
    review_group(store, old_run['id'], 'A',
                 {'revision': 0, 'status': 'APPROVED', 'note': 'A 组已签发'})

    new = csv_bytes([
        audit('A1', 'A'),
        ['BAD9', '???', 'initial', '0', '0', '0', '0', '0', '无法认组'],
    ])
    new_run = execute(store, new)
    assert new_run['handoff']['global_hold'] is True
    assert new_run['handoff']['conclusions']['A'] == 'APPROVED'
