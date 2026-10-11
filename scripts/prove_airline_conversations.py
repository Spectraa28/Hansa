"""Six development conversations through the running API; paid stages never restart automatically.

Requires the reviewed GitHub fork import. Imported source executes only in Docker.
Local server administration creates a temporary owner session, revoked on exit.
"""
import argparse
import json
import time

import httpx

from backend.app.config import ROOT, Settings
from backend.app.database import Database
from backend.app.sessions import SESSION_COOKIE, create_session, delete_session

SHA = '6af0b4caf37dca4526dfd98e9fbd8ce36e7eeb22'
TOOLS = ['transfer_to_flight_modification', 'transfer_to_lost_baggage', 'transfer_to_flight_cancel',
         'transfer_to_flight_change', 'transfer_to_triage', 'initiate_refund', 'initiate_flight_credits',
         'initiate_baggage_search', 'valid_to_change_flight', 'change_flight', 'escalate_to_agent', 'case_resolved']
CAPS = {'onboarding': 1.0, 'baseline': 2.0, 'investigation': 1.0}


def stage_cost(stage, report):
    if stage == 'baseline':
        usages = [run for task in report['tasks'] for run in task['runs']]
        if any(run['unknown_cost_calls'] or (run['model_calls'] and run['cost_usd'] is None) for run in usages):
            raise ValueError('Unknown baseline cost; stop paid work.')
        return sum(run['cost_usd'] or 0 for run in usages)
    usages = [report['result'].get(name, {}) for name in ('agent_usage', 'target_usage')]
    if any(usage.get('unknown_cost_calls') or (usage.get('calls') and usage.get('estimated_cost_usd') is None) for usage in usages):
        raise ValueError('Unknown stage cost; stop paid work.')
    return sum(usage.get('estimated_cost_usd') or 0 for usage in usages)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('import_id')
    parser.add_argument('--stage', choices=['prepare', *CAPS, 'report'], required=True)
    parser.add_argument('--retry', action='store_true', help='Explicitly retry a failed agent stage; retain and charge prior attempts')
    args = parser.parse_args()
    settings = Settings.from_env()
    database = Database(settings.database_path)
    with database.connect() as db:
        row = db.execute('SELECT * FROM repository_imports WHERE id=?', (args.import_id,)).fetchone()
    if not row or row['status'] != 'ready' or row['repository_name'].split('/')[-1] != 'swarm' or row['connection_generation'] == 'local-fixture' or row['commit_sha'] != SHA:
        raise SystemExit('Requires the real, ready GitHub Swarm fork at the reviewed SHA.')
    path = ROOT / 'var' / ('airline-conversations-' + args.import_id + '.json')
    evidence = json.loads(path.read_text()) if path.exists() else {'import_id': args.import_id, 'commit_sha': SHA, 'fixture': False, 'total_budget_usd': 5.0, 'stages': {}}
    token, csrf = create_session(database, row['user_id'], None)
    try:
        with httpx.Client(base_url='http://127.0.0.1:8000', cookies={SESSION_COOKIE: token}, headers={'X-CSRF-Token': csrf}, timeout=60, trust_env=False) as client:
            prefix = '/github/imports/' + args.import_id
            def api(method, endpoint, body=None):
                response = client.request(method, prefix + endpoint, json=body)
                if response.status_code >= 400:
                    raise RuntimeError(f'API {endpoint}: {response.status_code}: {response.text[:300]}')
                return response.json()
            def save():
                path.write_text(json.dumps(evidence, indent=2, allow_nan=False))
                path.chmod(0o600)
            if args.stage == 'prepare':
                if evidence['stages']:
                    raise SystemExit('Pipeline already started; do not replace its frozen contract.')
                config = api('GET', '/inspection')
                selected = (config.get('configuration') or {}).get('litellm_model') or 'claude-sonnet-4.6'
                detected = {item['value'] for item in config['findings']['findings'] if item['kind'] == 'tool'}
                if not set(TOOLS) <= detected:
                    raise SystemExit('Reinspect to detect all airline tools before preparing.')
                config = api('POST', '/configuration', {'revision': config['revision'], 'commit_sha': SHA,
                    'python_version': '>=3.10', 'dependency_manifests': ['setup.cfg'], 'entrypoint': 'python examples/airline/main.py',
                    'model_provider': 'openai', 'model_id': 'gpt-4o', 'litellm_model': selected, 'approved_tools': TOOLS})
                previous = api('GET', '/contract')
                body = json.loads((ROOT / 'examples/contracts/swarm_airline.json').read_text())
                body.update(configuration_revision=config['configuration_revision'], base_version=previous['version'])
                contract = api('POST', '/contract', body)
                contract = api('POST', '/contract/confirm', {'version': contract['version'], 'configuration_revision': config['configuration_revision']})
                evidence.update(configuration=config, contract=contract)
                save()
                print(json.dumps({'prepared': True, 'baseline_model': selected, 'tasks': 6, 'stage_thresholds': CAPS, 'reserve_usd': 1.0}), flush=True)
                return
            if 'contract' not in evidence:
                raise SystemExit('Prepare and review the contract first.')
            for stage, saved in evidence['stages'].items():
                endpoint = '/baseline-jobs/' if stage == 'baseline' else '/agent-jobs/'
                saved['report'] = api('GET', endpoint + saved['id'])
                saved['cost_usd'] = stage_cost(stage, saved['report']) + sum(stage_cost(stage, attempt) for attempt in saved.get('attempts', []))
            total = sum(saved['cost_usd'] for saved in evidence['stages'].values())
            evidence['recorded_cost_usd'] = total
            save()
            if args.stage == 'report':
                print(json.dumps({'recorded_cost_usd': total, 'stages': {stage: {'id': saved['id'], 'status': saved['report']['status'], 'cost_usd': saved['cost_usd']} for stage, saved in evidence['stages'].items()}}), flush=True)
                return
            previous_stage = {'baseline': 'onboarding', 'investigation': 'baseline'}.get(args.stage)
            if previous_stage and (previous_stage not in evidence['stages'] or evidence['stages'][previous_stage]['report']['status'] not in {'ready', 'completed'}):
                raise SystemExit('Previous stage must complete successfully first.')
            if any(saved['report']['status'] == 'running' for saved in evidence['stages'].values()):
                raise SystemExit('A stage is already running; use --stage report.')
            attempts = []
            prior = evidence['stages'].get(args.stage)
            if prior:
                if not args.retry or args.stage == 'baseline' or prior['report']['status'] not in {'failed', 'blocked'}:
                    raise SystemExit('Stage already started. Read its evidence; failed agent stages require an explicit --retry.')
                attempts = [*prior.get('attempts', []), prior['report']]
            current = api('GET', '/contract')
            if current['stale'] or current['status'] != 'confirmed' or current['version'] != evidence['contract']['version']:
                raise SystemExit('Configuration or contract changed; do not run this frozen pipeline.')
            allowance = min(CAPS[args.stage], 5.0 - 1.0 - total)
            if allowance <= 0:
                raise SystemExit('Pipeline budget exhausted; reserve preserved.')
            if args.stage == 'baseline':
                if total + 2.0 > 4.0:
                    raise SystemExit('Insufficient budget for the frozen baseline contract.')
                report = api('POST', '/baseline', {'repetitions': 2})
                job_id = report['baseline_id']
            else:
                body = {'max_spend_usd': allowance}
                if args.stage == 'investigation':
                    body['baseline_id'] = evidence['stages']['baseline']['id']
                report = api('POST', '/' + args.stage, body)
                job_id = report['job_id']
            evidence['stages'][args.stage] = {'id': job_id, 'report': report, 'attempts': attempts}
            save()
            print(json.dumps({'stage': args.stage, 'id': job_id, 'max_spend_usd': allowance}), flush=True)
            after = 0
            endpoint = '/baseline-jobs/' if args.stage == 'baseline' else '/agent-jobs/'
            while True:
                for event in api('GET', endpoint + job_id + '/events?after=' + str(after))['events']:
                    after = event['id']
                    print(json.dumps({'event': event['kind'], 'data': {k: v for k, v in event['data'].items() if k in {'text','name','status','reason','task_id','repetition','cost_usd','stop_reason'}}})[:1200], flush=True)
                report = api('GET', endpoint + job_id)
                evidence['stages'][args.stage]['report'] = report
                save()
                if report['status'] != 'running':
                    break
                time.sleep(2)
            cost = stage_cost(args.stage, report)
            evidence['stages'][args.stage]['cost_usd'] = cost + sum(stage_cost(args.stage, attempt) for attempt in attempts)
            evidence['recorded_cost_usd'] = total + cost
            save()
            print(json.dumps({'stage': args.stage, 'status': report['status'], 'cost_usd': cost, 'total_usd': total + cost, 'evidence': str(path)}), flush=True)
    finally:
        delete_session(database, token)


if __name__ == '__main__':
    main()
