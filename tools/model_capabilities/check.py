"""Offline MAAS-9 input inventory validator; no inference or authority side effects."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def validate_profile(profile):
    Draft202012Validator(read(ROOT/'profile.schema.json')).validate(profile)
    if profile['source_kind'] == 'SelfHosted':
        c=profile['configuration']
        required={'groups','pods_per_group','gpus_per_pod','tp','pp','dp','ep'}
        if not required <= c.keys() or any(type(c[k]) is not int or c[k]<1 for k in required):
            raise ValueError('invalid parallelism shape')
        if c['tp']*c['pp'] != c['pods_per_group']*c['gpus_per_pod']:
            raise ValueError('parallelism does not match group GPU allocation')
        if c['pp'] != 1 or c['dp'] != 1 or c['ep'] != 1:
            raise ValueError('outside initial controlled profile')
    elif profile['engine'] is not None:
        raise ValueError('external/fixture profile must not create engine workload')
    return True

def lock_conditions(profile):
    """Missing input inventory only. Completing it would still not authorize execution."""
    validate_profile(profile)
    missing=['member_approval','verified_total_token_bounds','actual_gateway_and_kernel_evidence']
    if profile['source_kind']=='ControlledFixture': missing.append('fixture_is_not_a_real_model')
    for key,value in profile['locks'].items():
        if profile['source_kind']!='SelfHosted' and key in {'image_digest','weights_manifest_sha256','tokenizer_assets_sha256','effective_template_sha256','gpu_model','gpu_count','gpu_memory_bytes_each','intra_node_links','inter_node_network','driver_version','cuda_pytorch_nccl_manifest'}:
            continue
        if value is None: missing.append('missing:'+key)
    if profile['model']['model_id'] is None: missing.append('accurate_model_unselected')
    return missing+['review_required:'+x for x in profile['conflicts']]

def project_usage(adapter,raw):
    """Bounded synthetic projection oracle; no pricing, finalization or adapter execution."""
    if adapter=='sglang-v0.5.18':
        c=raw.get('prompt_tokens_details')
        cached=c.get('cached_tokens') if isinstance(c,dict) else None
        reasoning=raw.get('reasoning_tokens')
    elif adapter=='deepseek-documentation-candidate':
        cached=raw.get('prompt_cache_hit_tokens')
        d=raw.get('completion_tokens_details')
        reasoning=d.get('reasoning_tokens') if isinstance(d,dict) else None
    else: raise ValueError('unknown adapter profile')
    result=dict(input_tokens=raw.get('prompt_tokens'),output_tokens=raw.get('completion_tokens'),total_tokens=raw.get('total_tokens'),input_cached_tokens=cached,reasoning_tokens=reasoning)
    if any(v is not None and (type(v) is not int or v<0) for v in result.values()): raise ValueError('invalid usage count')
    i,o,t,c,r=result.values()
    if i is not None and o is not None and t is not None and i+o!=t: raise ValueError('contradictory total')
    if i is not None and c is not None and c>i: raise ValueError('invalid cache subset')
    if o is not None and r is not None and r>o: raise ValueError('invalid reasoning subset')
    return result

def perf_shapes(profile):
    plan=read(ROOT/'evidence/perf-plan-v0.4.json'); cap=profile['context']['proposed_service_tokens']
    return [{'shape':x['id'],'planned_input_plus_output':x['input_tokens']+x['output_cap_tokens'],
             'fits_proposal_arithmetic_only':None if cap is None else x['input_tokens']+x['output_cap_tokens']<=cap,
             'real_model_validation':'not_run'} for x in plan['shapes']]

def inspect(source_root=None):
    checks=[]
    def check(name,condition,scope):
        checks.append(dict(name=name,passed=bool(condition),scope=scope))
    source=read(ROOT/'evidence/upstream-sources.json')
    for item in source['files']:
        check('pinned/'+item['id'],len(item['revision'])==40 and len(item['sha256'])==64,'fixed_source_inventory')
        if source_root:
            path=source_root/item['file']
            check('cached_source_sha/'+item['id'],path.is_file() and sha(path)==item['sha256'],'source_integrity')
    for item in read(ROOT/'evidence/contract-provenance.json')['files']:
        check('contract_sha/'+item['file'],sha(ROOT/'evidence'/item['file'])==item['sha256'],'source_integrity')
    facts=read(ROOT/'evidence/model-metadata.json')
    check('context_declarations_kept_distinct',facts['model_max_position_embeddings']==131072 and facts['tokenizer_model_max_length']==16384 and facts['effective_context_tokens'] is None,'metadata')
    check('BOS_conflict_not_silently_resolved',facts['config_bos_token_id']!=facts['generation_bos_token_id'],'metadata')
    check('template_is_not_effective_runtime_template',facts['template_adds_thinking_prefix'] and facts['tokenizer_assets_sha256'] is None,'metadata')
    check('KV_shape_arithmetic_not_memory_measurement',2*facts['num_layers']*facts['kv_heads']*facts['head_dim']*2==57344,'arithmetic')
    consumers=read(ROOT/'evidence/consumer-map.json')
    check('perf_snapshot_sha',sha(ROOT/'evidence/perf-plan-v0.4.json')==consumers['perf_plan_sha256'],'source_integrity')
    check('current_and_proposed_protocols_separate',consumers['current_protocols']['terminal']=='3.0' and consumers['d1_proposal']['terminal']=='3.1' and consumers['d1_proposal']['state']=='consumer_migration_pending','version_boundary')
    profiles=[]
    for path in sorted((ROOT/'profiles').glob('*.json')):
        p=read(path); validate_profile(p); missing=lock_conditions(p)
        profiles.append(dict(id=p['id'],scope=p['scope'],real_execution_allowed=False,lock_conditions=missing,perf_shape_assessment=perf_shapes(p)))
        check(p['id']+'/execution_disabled',p['execution_enabled'] is False and p['hard_budget']['status']=='unverified','profile_guard')
        check(p['id']+'/has_blocking_conditions',bool(missing),'profile_guard')
    for case in read(ROOT/'vectors/adapter.json')['cases']:
        check('adapter/'+case['id'],project_usage(case['adapter'],case['raw'])==case['expected'],'synthetic_projection')
    api=read(ROOT/'evidence/current-openapi.json')
    public={'$ref':'#/components/schemas/ChatRequest','components':api['components']}
    pv=Draft202012Validator(public)
    for q in read(ROOT/'vectors/quality.json')['cases']:
        req={'model':'model-a','messages':q['messages'],'max_tokens':40}
        check(q['id']+'/request_shape',pv.is_valid(req),'public_schema_not_quality_score')
    req={'model':'model-a','messages':[{'role':'user','content':'synthetic'}],'stream':True,'stream_options':{'include_usage':True}}
    check('public_usage_option_rejected',not pv.is_valid(req),'public_schema')
    current=Draft202012Validator(read(ROOT/'evidence/current-terminal-3.0.schema.json'))
    proposed=Draft202012Validator(read(ROOT/'evidence/proposed-terminal-3.1.schema.json'))
    for path in sorted((ROOT/'vectors').glob('*.current-3.0.json')):
        check(path.stem+'/current',current.is_valid(read(path)),'current_schema_only')
    for path in sorted((ROOT/'vectors').glob('*.proposal-3.1.json')):
        value=read(path)
        check(path.stem+'/proposal_shape',proposed.is_valid(value),'proposed_schema_only')
        check(path.stem+'/strict_current_rejects',not current.is_valid(value),'version_boundary')
    return {'report_version':'0.3','checked_at_utc':datetime.now(timezone.utc).isoformat(),'python':platform.python_version(),'jsonschema':importlib.metadata.version('jsonschema'),
            'scope':'offline_source_metadata_and_synthetic_vectors','real_execution_allowed':False,
            'summary':{'total':len(checks),'passed':sum(x['passed'] for x in checks),'failed':sum(not x['passed'] for x in checks)},'checks':checks,'profiles':profiles,
            'not_executed':['engine_import_or_launch','tokenizer_asset_load','model_generation','image_pull','GPU_or_NCCL','Higress_adapter','durable_call_or_settlement','cancellation_or_capacity_recovery','model_quality','performance'],'d1_state':'proposal_consumer_migration_pending'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,help='Optional local captured source directory; never fetched automatically')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--require-locked',action='store_true',help='Exit 2 while real input locks remain incomplete; never grants permission')
    args=parser.parse_args()
    try:
        report=inspect(args.source_root)
        if report['summary']['failed'] or args.require_locked:
            print('offline validation failed or real input locks incomplete',file=sys.stderr)
            return 2
        if args.output:
            inputs={p.resolve() for p in ROOT.rglob('*') if p.is_file()}
            if args.output.resolve() in inputs:
                raise ValueError('output may not overwrite input')
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report['summary']))
        return 0
    except Exception as exc:
        # No profile values or credentials in error output.
        print('capability input rejected: '+type(exc).__name__,file=sys.stderr)
        return 2

if __name__=='__main__': sys.exit(main())