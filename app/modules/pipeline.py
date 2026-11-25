from app.business import DomainIssue
from app.handoff import build_handoff, lineage
from app.intake.service import inspect
from app.modules.calculate import compute
from app.modules.grouping import case_groups
from app.modules.policy import policy
from app.modules.prepare import prepare
from app.modules.reconcile import balance


def evaluate(rows, stage):
    case = {'case':rows[0]['case'],'records':[r['record'] for r in rows], 'status':'READY'}
    try:
        case['prep'], payload = prepare(rows)
        if stage >= 3:
            case['measure'] = compute(payload)
        if stage >= 4:
            case.update(policy(case['measure']))
    except DomainIssue as error:
        case['status'] = error.code
    return case


def run(data, stage=5):
    intake = inspect(data)
    output = {'intake': {k:v for k,v in intake.items() if k!='rows'}}
    output['lineage'] = lineage(intake)
    if stage == 1:
        return output
    cases = [evaluate(rows, stage) for _, rows in case_groups(intake['rows'])]
    output['cases'] = cases
    if stage >= 5:
        handoff = build_handoff(intake, cases)
        for item in handoff['groups']:
            case = next((candidate for candidate in cases if candidate.get('case') == item['group']), None)
            if case is not None:
                case['handoff'] = item
                case['handoff_status'] = item['status']
                case['releasable'] = item['releasable']
        output['handoff'] = handoff
        output['group_handoff'] = handoff
        output['group_results'] = handoff['groups']
        output['balance'] = balance(intake,cases)
        output['balance']['handoff'] = handoff
        output['balance']['group_conclusions'] = handoff['groups']
    return output
