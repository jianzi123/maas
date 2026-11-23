"""Offline qualification. Preserve every planned row; never estimate a gain."""
import argparse, json, math, statistics
from collections import Counter
from pathlib import Path
from cadence_protocol import digest, write_json
from reference_protocol import CONFIG, load, match, stratum


def evaluate(plan, rows, bank, runtime, queries, ios, gates, root, check_files=True):
    errors = []
    def require(ok, message):
        if not ok: errors.append(message)
    require(check_files, 'complete vector validation required')
    expected = {r['id']: r for r in plan['rows']}
    by_id = {r['id']: r for r in rows}
    require(len(by_id) == len(rows) == 128 and set(by_id) == set(expected), 'planned identities/denominator')
    clock = runtime.get('clock_scope') if runtime else None
    require(runtime is not None, 'runtime missing')
    if runtime:
        require(runtime.get('plan_sha256') == digest(plan), 'runtime plan')
        require(runtime.get('root_kind') == 'only_initial_boot_event_observation', 'root kind')
        require(runtime.get('frozen_ns', 0) > runtime.get('root_observed_done_ns', 0), 'runtime freeze')
    qmap = {q['id']: q for q in queries}; imap = {i['id']: i for i in ios}
    require(len(qmap) == len(queries), 'duplicate query')
    require(len(imap) == len(ios), 'duplicate IO')
    for item in queries + ios:
        require(item.get('clock_scope') == clock and 0 < item['begin_ns'] <= item['end_ns'], 'observer clock/order')
    used_queries = set(); prev_id = None
    prev_done = runtime.get('root_observed_done_ns') if runtime else None
    missing_seen = False; details = []; measured = 0
    for scheduled in plan['rows']:
        row = by_id.get(scheduled['id'])
        if row is None: continue
        require(all(row.get(k) == v for k, v in scheduled.items()), 'frozen row identity: ' + row['id'])
        require(row.get('clock_scope') == clock, 'row clock: ' + row['id'])
        if row.get('status') != 'measured':
            missing_seen = True
            require(row.get('status') == 'missing' and row.get('calls_completed') == 0, 'invalid/incomplete row')
            details.append(dict(scheduled, status=row.get('status'), matched=False))
            continue
        measured += 1
        require(not missing_seen, 'measured after missing')
        require(row.get('previous_id') == prev_id and row.get('previous_done_ns') == prev_done,
                'previous_done continuity: ' + row['id'])
        order = [row.get(k, -1) for k in ('previous_done_ns','prepare_begin_ns','ready_ns','submit_ns','enqueue_ns','done_ns','bookkeeping_end_ns')]
        require(all(isinstance(t, int) and t > 0 for t in order) and order == sorted(order), 'row timing order: ' + row['id'])
        require(row.get('calls_completed') == 10 and isinstance(row.get('event_ns'), (int,float))
                and math.isfinite(row['event_ns']) and row['event_ns'] > 0, 'event/call validity')
        if row['mode'] == 'query':
            q = qmap.get(row.get('query_id')); used_queries.add(row.get('query_id'))
            require(q is not None, 'query missing')
            if q:
                require(q.get('row_id') == row['id'] and row['ready_ns'] <= q['begin_ns'] <= q['end_ns'] <= row['submit_ns'], 'query relation/order')
                require(q.get('result', {}).get('returncode') == 0 and bool(q.get('result', {}).get('csv')), 'query failed')
        else:
            require(row.get('query_id') is None, 'unexpected query')
        if row['role'] == 'boundary_first':
            io = imap.get(row.get('io_id'))
            require(io is not None, 'boundary IO missing')
            if io:
                require(io.get('reason') == 'pair-boundary' and prev_done <= io['begin_ns'] <= io['end_ns'] <= row['prepare_begin_ns'], 'boundary IO order')
                require(prev_id in io.get('row_ids', []), 'preceding bookkeeping not archived')
        else: require(row.get('io_id') is None, 'interior/transition IO identity')
        gap = row['submit_ns'] - row['previous_done_ns']
        detail = dict(scheduled, status='measured', gap_ns=gap, event_ns=row['event_ns'])
        if scheduled['qualify'] and bank:
            key = stratum(row); target = bank.get('targets_ns', {}).get(key)
            require(target is not None, 'target missing')
            require(row.get('bank_sha256') == digest(bank) and bank['frozen_ns'] < row['prepare_begin_ns'], 'bank freeze/hash')
            if target is not None:
                detail.update(match(gap, target))
                if row['mode'] == 'idle':
                    a, b = row.get('sleep_begin_ns'), row.get('sleep_end_ns')
                    require(isinstance(a,int) and isinstance(b,int) and row['ready_ns'] <= a <= b <= row['submit_ns'], 'idle order')
                    if isinstance(a,int): require(row.get('sleep_requested_ns') == max(0, prev_done + target - a), 'idle deadline')
        details.append(detail); prev_id=row['id']; prev_done=row['done_ns']
    require(used_queries == set(qmap), 'orphan query retained')
    refs = [r for r in rows if r.get('phase') == 'reference' and r.get('status') == 'measured']
    reference_rows = [r for r in refs if r['role'] != 'cell_transition']
    targets = {}
    for key in sorted({stratum(r) for r in reference_rows}):
        values = [r['submit_ns']-r['previous_done_ns'] for r in reference_rows if stratum(r)==key]
        require(len(values)==3, 'reference stratum count: '+key)
        targets[key]=int(statistics.median(values))
    require(bank is not None, 'bank missing')
    if bank:
        require(bank.get('schema') == 'reference-bank1' and bank.get('clock_scope') == clock and bank.get('plan_sha256') == digest(plan), 'bank identity')
        require(bank.get('targets_ns') == targets and len(targets)==16, 'common prior targets')
        require(bank.get('reference_row_ids') == [r['id'] for r in reference_rows] and bank.get('reference_rows_sha256') == digest(refs), 'reference frozen digest')
        require(all(0 < v <= CONFIG['max_target_ns'] for v in targets.values()), 'target bound')
        require(bank.get('match_abs_ns') == CONFIG['match_abs_ns'] and bank.get('match_relative') == CONFIG['match_relative'] and bank.get('same_target_for_query_and_idle') is True, 'tolerance/target policy')
        require(all(r['bookkeeping_end_ns'] < bank['frozen_ns'] for r in refs), 'bank before reference complete')
    gate_ids = [(g.get('cell_id'),g.get('phase')) for g in gates]
    want = {(f'R01/{s}/B{b}', f'{p}-{edge}') for s in CONFIG['scopes'] for b in CONFIG['batches'] for p in ('reference','holdout') for edge in ('before','after')}
    require(len(gate_ids)==16 and set(gate_ids)==want, 'state gate coverage/identity')
    if check_files:
        from analyze_kv_cadence import validate_gate
        for gate in gates:
            try: validate_gate(gate,Path(root))
            except (ValueError, OSError, KeyError, TypeError) as error: errors.append('state gate: '+str(error))
    if check_files:
        def read_file(name, default):
            path=Path(root)/name
            return json.loads(path.read_text()) if path.exists() else default
        cells=read_file('cells.json',[])
        cmap={(c.get('phase'),c.get('scope'),c.get('batch')):c for c in cells}
        wanted={(p,s,b) for p in ('reference','holdout') for s in CONFIG['scopes'] for b in CONFIG['batches']}
        require(len(cells)==8 and set(cmap)==wanted,'cell coverage')
        for row in rows:
            if row.get('status')!='measured':continue
            c=cmap.get((row['phase'],row['scope'],row['batch']))
            require(c is not None,'cell missing')
            if c:
                require(c.get('clock_scope')==clock and c.get('input_sha256')==row.get('input_sha256')
                        and isinstance(c.get('input_sha256'),str) and len(c['input_sha256'])==64,
                        'input/cell clock identity')
                require(c.get('begin_ns',0)<=c.get('ready_ns',0)<=row['prepare_begin_ns'],'cell ready')
        end=read_file('final-invariants.json',{})
        require(end.get('parameters_unchanged') is True and end.get('graphs_unchanged') is True,'final invariants absent/failed')
        res=end.get('resources',{})
        require(res.get('free',0)>=1073741824 and res.get('reserved',1)>0
                and res.get('reserved',1)<=res.get('total',0)*.20,'final resources')
    holds=[d for d in details if d['qualify']]
    strata={key: {'planned':4,'measured':sum(d['status']=='measured' for d in holds if stratum(d)==key),
                  'matched':sum(d.get('matched',False) for d in holds if stratum(d)==key)} for key in targets}
    matched=sum(d.get('matched',False) for d in holds)
    return {'schema':'ELIT01-reference-qualification1','plan_sha256':digest(plan),
            'measured_rows':measured,'planned_rows':128,'planned_calls':1280,
            'completed_calls':sum(r.get('calls_completed',0) for r in rows),
            'holdout_planned':64,'matched_holdout':matched,'strata':strata,
            'status_counts':dict(Counter(r.get('status') for r in rows)),
            'integrity_valid':not errors,'errors':errors,'qualified':not errors and len(holds)==64 and matched==64,
            'details':details,'host_gap_is_physical_GPU_idle':False,
            'root_cause':'unknown','stable_gain':'unknown','main_comparison_executed':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();plan=load(a.plan)
    def read(name, default):
        path=a.root/name
        return json.loads(path.read_text()) if path.exists() else default
    rows=[json.loads(s) for s in (a.root/'ledger.jsonl').read_text().splitlines()]
    report=evaluate(plan,rows,read('frozen-targets.json',None),read('runtime-manifest.json',None),
                    read('queries.json',[]),read('io-events.json',[]),read('gates.json',[]),a.root)
    write_json(a.output,report,exclusive=True)
    print(json.dumps({k:report[k] for k in ('integrity_valid','qualified','measured_rows','matched_holdout')}))
    return 0 if report['integrity_valid'] else 2
if __name__=='__main__':raise SystemExit(main())
