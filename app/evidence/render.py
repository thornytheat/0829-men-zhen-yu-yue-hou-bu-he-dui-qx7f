import json


def artifact(run):
    packet = {
        'schema': 'review-evidence/1',
        'manifest': run['report']['manifest'],
        'balance': run['report']['balance'],
        'cases': run['report']['cases'],
        'intake': run['report']['intake'],
        'handoff': run['report'].get('handoff'),
        'lineage': run['report'].get('lineage'),
        'group_reviews': run.get('group_reviews', {}),
        'board_id': run.get('board_id'),
        'review': {key:run[key] for key in ('status','revision','note','reviewed')},
    }
    return (json.dumps(packet, ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
