import json

from flask import Blueprint, Response, current_app, jsonify, request

from app.business import DomainIssue
from app.evidence.render import artifact
from app.inputs import read_input
from app.modules.pipeline import run
from app.review.service import (
    DEFAULT_BOARD,
    board_handoff,
    execute,
    present_run,
    review,
    review_group,
    update_source,
)

api = Blueprint('api',__name__,url_prefix='/api')
STAGES = {'intake':1,'prepare':2,'calculate':3,'policy':4,'balance':5}


@api.post('/stages/<stage>')
def preview(stage):
    if stage not in STAGES:
        raise DomainIssue('STAGE_UNKNOWN')
    return jsonify(run(read_input(),STAGES[stage]))


@api.route('/runs',methods=['GET','POST'])
def runs():
    store = current_app.extensions['runs']
    if request.method == 'GET':
        return jsonify(items=store.list())
    board_id = request.form.get('board_id') or request.form.get('source_id') or DEFAULT_BOARD
    return jsonify(execute(store,read_input(),board_id=board_id))


@api.route('/runs/<run_id>', methods=['GET','PATCH'])
def batch(run_id):
    store = current_app.extensions['runs']
    if request.method == 'GET':
        return jsonify(present_run(store, run_id))
    values = request.get_json(silent=True)
    if not isinstance(values, dict) and request.form:
        values = {key: request.form.get(key) for key in ('group', 'case', 'group_id', 'status', 'decision', 'note')}
        values['revision'] = request.form.get('revision', type=int)
    if isinstance(values, dict) and any(values.get(key) for key in ('group','case','group_id','group_code')):
        group_id = values.get('group_id') or values.get('group') or values.get('case') or values.get('group_code')
        return jsonify(review_group(store, run_id, group_id, values))
    return jsonify(review(store,run_id,values))


@api.route('/runs/<run_id>/groups/<group_id>', methods=['GET','PATCH','POST'])
def run_group(run_id, group_id):
    store = current_app.extensions['runs']
    if request.method == 'GET':
        presented = present_run(store, run_id)
        target = next((item for item in presented['handoff']['groups']
                       if item['group'] == group_id), None)
        if target is None:
            raise DomainIssue('GROUP_NOT_FOUND')
        return jsonify(target)
    values = request.get_json(silent=True)
    if not isinstance(values, dict):
        # HTML-style form posts can also identify the decision in form data.
        values = {'status': request.form.get('status') or request.form.get('decision'),
                  'note': request.form.get('note'),
                  'revision': request.form.get('revision', type=int)}
    return jsonify(review_group(store, run_id, group_id, values))


@api.route('/runs/<run_id>/groups', methods=['GET','PATCH','POST'])
def run_groups(run_id):
    if request.method == 'GET':
        return jsonify(present_run(current_app.extensions['runs'], run_id)['handoff']['groups'])
    values = request.get_json(silent=True)
    if not isinstance(values, dict):
        values = {'status': request.form.get('status') or request.form.get('decision'),
                  'note': request.form.get('note'),
                  'revision': request.form.get('revision', type=int),
                  'group': request.form.get('group') or request.form.get('group_id')}
    group_id = values.get('group_id') or values.get('group') or values.get('case')
    return jsonify(review_group(current_app.extensions['runs'], run_id, group_id, values))


@api.get('/runs/<run_id>/handoff')
@api.get('/runs/<run_id>/conclusions')
def run_handoff(run_id):
    presented = present_run(current_app.extensions['runs'], run_id)
    return jsonify(presented['handoff'])


@api.post('/runs/<run_id>/source')
@api.post('/runs/<run_id>/sources')
@api.post('/runs/<run_id>/update')
def run_source_update(run_id):
    store = current_app.extensions['runs']
    return jsonify(update_source(store, run_id, read_input()))


@api.route('/runs/<run_id>/groups/<group_id>/certificate')
@api.route('/runs/<run_id>/groups/<group_id>/evidence')
def run_group_certificate(run_id, group_id):
    store = current_app.extensions['runs']
    reviews = store.list_run_group_reviews(run_id)
    state = reviews.get(group_id) or store.get_group_review(store.board_for_run(run_id) or DEFAULT_BOARD, group_id)
    certificate_id = (state or {}).get('certificate_id')
    if not certificate_id:
        raise DomainIssue('CERTIFICATE_NOT_FOUND')
    packet = store.load_certificate(certificate_id)
    body = (json.dumps(packet['artifact'], ensure_ascii=False,
                       sort_keys=True, indent=2) + '\n').encode('utf-8')
    return Response(body, mimetype='application/json', headers={
        'Content-Disposition': f'attachment; filename="group-{group_id}-certificate.json"',
        'Cache-Control': 'no-store',
    })


@api.post('/runs/<run_id>/sign')
@api.post('/runs/<run_id>/issue')
def sign_run_alias(run_id):
    values = request.get_json(silent=True) or {}
    values.setdefault('status', 'APPROVED')
    group_id = values.get('group') or values.get('group_id') or values.get('case')
    if group_id:
        return jsonify(review_group(current_app.extensions['runs'], run_id, group_id, values))
    return jsonify(review(current_app.extensions['runs'], run_id, values))


@api.post('/runs/<run_id>/approve')
def approve_run_alias(run_id):
    values = request.get_json(silent=True) or {}
    group_id = values.get('group') or values.get('group_id') or values.get('case')
    if group_id:
        values.setdefault('status', 'APPROVED')
        return jsonify(review_group(current_app.extensions['runs'], run_id, group_id, values))
    values.setdefault('status', 'APPROVED')
    return jsonify(review(current_app.extensions['runs'], run_id, values))


@api.post('/runs/<run_id>/hold')
def hold_run_alias(run_id):
    values = request.get_json(silent=True) or {}
    group_id = values.get('group') or values.get('group_id') or values.get('case')
    if group_id:
        values.setdefault('status', 'HELD')
        return jsonify(review_group(current_app.extensions['runs'], run_id, group_id, values))
    values.setdefault('status', 'HELD')
    return jsonify(review(current_app.extensions['runs'], run_id, values))


@api.post('/runs/<run_id>/groups/<group_id>/approve')
def approve_run_group(run_id, group_id):
    values = request.get_json(silent=True) or {}
    values.setdefault('status', 'APPROVED')
    return jsonify(review_group(current_app.extensions['runs'], run_id, group_id, values))


@api.post('/runs/<run_id>/groups/<group_id>/hold')
def hold_run_group(run_id, group_id):
    values = request.get_json(silent=True) or {}
    values.setdefault('status', 'HELD')
    return jsonify(review_group(current_app.extensions['runs'], run_id, group_id, values))


@api.route('/boards', methods=['GET','POST'])
def boards():
    store = current_app.extensions['runs']
    if request.method == 'GET':
        return jsonify(items=store.list_boards())
    board_id = request.form.get('board_id') or request.form.get('source_id')
    result = execute(store, read_input(), board_id=board_id or DEFAULT_BOARD)
    return jsonify(result)


@api.get('/boards/<board_id>')
def board(board_id):
    return jsonify(board_handoff(current_app.extensions['runs'], board_id))


@api.post('/boards/<board_id>/sources')
@api.post('/boards/<board_id>/runs')
def board_source(board_id):
    store = current_app.extensions['runs']
    return jsonify(execute(store, read_input(), board_id=board_id))


@api.route('/boards/<board_id>/groups/<group_id>', methods=['GET','PATCH','POST'])
def board_group(board_id, group_id):
    store = current_app.extensions['runs']
    if request.method == 'GET':
        result = board_handoff(store, board_id)
        target = next((item for item in result['handoff']['groups']
                       if item['group'] == group_id), None)
        if target is None:
            raise DomainIssue('GROUP_NOT_FOUND')
        return jsonify(target)
    values = request.get_json(silent=True)
    if not isinstance(values, dict):
        values = {'status': request.form.get('status') or request.form.get('decision'),
                  'note': request.form.get('note'),
                  'revision': request.form.get('revision', type=int)}
    values = dict(values)
    values['board_id'] = board_id
    return jsonify(review_group(store, board_id, group_id, values))


# Workbench/handoff aliases.  The default board is the current shift table.
@api.route('/workbench', methods=['GET','POST'])
@api.route('/handoff', methods=['GET','POST'])
def workbench_handoff():
    store = current_app.extensions['runs']
    if request.method == 'POST':
        return jsonify(execute(store, read_input(), board_id=DEFAULT_BOARD))
    try:
        return jsonify(board_handoff(store, DEFAULT_BOARD))
    except DomainIssue as error:
        if error.code == 'BOARD_NOT_FOUND' or error.code == 'RUN_NOT_FOUND':
            return jsonify(schema='group-handoff/1', groups=[], conclusion='尚未执行批次')
        raise


@api.route('/handoff/groups/<group_id>', methods=['PATCH','POST'])
def handoff_group(group_id):
    values = request.get_json(silent=True)
    if not isinstance(values, dict):
        values = {'status': request.form.get('status') or request.form.get('decision'),
                  'note': request.form.get('note'),
                  'revision': request.form.get('revision', type=int)}
    return jsonify(review_group(current_app.extensions['runs'], DEFAULT_BOARD, group_id, values))


@api.route('/group/<group_id>', methods=['PATCH','POST'])
def generic_singular_group(group_id):
    return handoff_group(group_id)


@api.route('/groups/<group_id>', methods=['PATCH','POST'])
def generic_group(group_id):
    return handoff_group(group_id)


@api.post('/groups/<group_id>/approve')
def generic_approve_group(group_id):
    values = request.get_json(silent=True) or {}
    values['status'] = 'APPROVED'
    return jsonify(review_group(current_app.extensions['runs'], DEFAULT_BOARD, group_id, values))


@api.post('/groups/<group_id>/hold')
def generic_hold_group(group_id):
    values = request.get_json(silent=True) or {}
    values['status'] = 'HELD'
    return jsonify(review_group(current_app.extensions['runs'], DEFAULT_BOARD, group_id, values))


@api.post('/sources')
def sources():
    source_id = request.form.get('source_id') or request.form.get('board_id') or DEFAULT_BOARD
    return jsonify(execute(current_app.extensions['runs'], read_input(), board_id=source_id))


@api.route('/sources/<source_id>', methods=['POST','PUT'])
def source_update(source_id):
    return jsonify(execute(current_app.extensions['runs'], read_input(), board_id=source_id))


@api.get('/certificates/<certificate_id>')
def certificate(certificate_id):
    packet = current_app.extensions['runs'].load_certificate(certificate_id)
    return jsonify(packet['artifact'])


@api.get('/certificates/<certificate_id>/evidence')
def certificate_evidence(certificate_id):
    packet = current_app.extensions['runs'].load_certificate(certificate_id)
    body = (json.dumps(packet['artifact'], ensure_ascii=False,
                       sort_keys=True, indent=2) + '\n').encode('utf-8')
    return Response(body, mimetype='application/json', headers={
        'Content-Disposition': f'attachment; filename="certificate-{certificate_id}.json"',
        'Cache-Control': 'no-store',
    })


@api.get('/runs/<run_id>/evidence')
def export(run_id):
    store = current_app.extensions['runs']
    report = present_run(store, run_id)
    return Response(artifact(report),mimetype='application/json', headers={
        'Content-Disposition':f'attachment; filename="review-{report["id"][:12]}.json"',
        'Cache-Control':'no-store',
    })
