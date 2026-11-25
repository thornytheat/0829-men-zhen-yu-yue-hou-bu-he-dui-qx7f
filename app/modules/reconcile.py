from collections import Counter

from app.handoff import build_handoff


def balance(intake, cases):
    accounted = intake['accepted'] + intake['rejected'] + intake['blank'] + intake['repeated']
    status = Counter(case['status'] for case in cases)
    ready = status.pop('READY', 0)
    observed = sum(len(case['records']) for case in cases)
    handoff = build_handoff(intake, cases)
    result = dict(input=intake['input'], accepted=intake['accepted'], isolated=intake['rejected'],
                ignored=intake['blank'] + intake['repeated'], accounted=accounted,
                balanced=accounted == intake['input'] and observed == intake['accepted'],
                ready=ready, pending=len(cases)-ready, issues=dict(sorted(status.items())),
                releasable=bool(cases) and ready==len(cases) and not intake['rejected'] and accounted==intake['input'] and observed==intake['accepted'])
    result['handoff'] = handoff
    result['group_handoff'] = handoff
    result['groups'] = handoff['groups']
    result['group_conclusions'] = handoff['groups']
    result['conclusions'] = handoff['conclusions']
    return result


# Common domain-language alias for callers that unit-test this module directly.
reconcile_groups = build_handoff
group_balance = balance
