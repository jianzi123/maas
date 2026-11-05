"""Independent static v2 checks; never product runtime or repair evidence."""
import argparse,hashlib,json,pathlib,subprocess
from jsonschema import Draft202012Validator,FormatChecker
p=argparse.ArgumentParser()
p.add_argument('--closure-dir',type=pathlib.Path,required=True)
p.add_argument('--output',type=pathlib.Path,required=True)
a=p.parse_args()
root=pathlib.Path(__file__).resolve().parents[2]
here=pathlib.Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
checks=[]
def check(name,ok):
    checks.append({'name':name,'passed':bool(ok)})
manifest=read(a.closure_dir/'manifest.json')
for name,digest in manifest.items():
    check('source hash '+name,hashlib.sha256((a.closure_dir/name).read_bytes()).hexdigest()==digest)
for name in ['MAAS-2-usage-receipt-diagnostic-0.1-draft.1.schema.json','MAAS-2-usage-receipt-diagnostic-examples.json']:
    check('frozen QA input '+name,(a.closure_dir/name).read_bytes()==(here/'contracts'/name).read_bytes())
old=read(here/'results.json')
expected=next(x['sha256'] for x in old['raw_files'] if x['file']=='qa-mysql-final.txt')
check('original failing runtime record retained',hashlib.sha256((here/'history/qa-v1-failures.txt').read_bytes()).hexdigest()==expected)
for name in ['internal/protocol/contracts/terminal.schema.json','internal/protocol/contracts/private.schema.json','tools/perf/contracts/observation.schema.json']:
    before=subprocess.check_output(['git','show','ca9fcdde6d2d28293b8a218935f88c08b1319dcf:'+name],cwd=root)
    check('product protocol unchanged '+name,before==(root/name).read_bytes())
schema=read(here/'contracts/MAAS-2-usage-receipt-diagnostic-0.1-draft.1.schema.json')
Draft202012Validator.check_schema(schema)
check('diagnostic meta-schema',True)
v=Draft202012Validator(schema,format_checker=FormatChecker())
examples=read(here/'contracts/MAAS-2-usage-receipt-diagnostic-examples.json')
for row in examples:
    check('diagnostic shape '+row['name'],v.is_valid(row['value'])==row['expected_valid'])
report={'kind':'independent_v2_static_only','passed':sum(x['passed'] for x in checks),'failed':sum(not x['passed'] for x in checks),
        'diagnostic_examples':len(examples),'checks':checks,
        'limits':['No diagnostic producer/storage/permissions executed','No backend repair SHA provided','Prior 53/80 checks and 35 database cases not rerun by this checker']}
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+chr(10)).encode('utf-8'))
print(json.dumps({k:report[k] for k in ['kind','passed','failed','diagnostic_examples']}))
raise SystemExit(bool(report['failed']))
