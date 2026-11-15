from pathlib import Path
import subprocess,json,collections,sys
import jsonschema
root=Path(__file__).resolve().parents[2]
qa=root/'test/independent'
sha='428d44e0b4f64ec628e6a945fd4b63a0e45c260b'
docs={}
for key,path in [('stable','console/contracts/openapi-v0.4.json'),('draft','console/contracts/query-recovery-draft.json')]:
    raw=subprocess.check_output(['git','-C',str(root),'show',sha+':'+path])
    (qa/(key+'.json')).write_bytes(raw)
    docs[key]=json.loads(raw)
for name in (sys.argv[1:] or ['qa-baseline-http','qa-independent-http']):
    events=json.loads((root/'artifacts'/(name+'.json')).read_text())
    counts=collections.Counter(); failures=[]
    for row in events:
        path=row['path'].split('?')[0];ver='stable'
        if row['http_status']>=400:schema='Error'
        elif path.endswith('/revisions'):schema='ReleaseRevisionPage';ver='draft'
        elif '/release-operations/' in path:schema='ReleaseOperation'
        elif path.endswith('/models'):schema='AdminModelList'
        elif row['method']!='GET':schema='ReleaseAccepted'
        elif path.endswith('/model-releases'):schema='ReleaseList'
        else:schema='ReleaseModelRelease'
        doc=docs[ver]
        validator=jsonschema.Draft202012Validator(doc['components']['schemas'][schema],resolver=jsonschema.RefResolver.from_schema(doc),format_checker=jsonschema.FormatChecker())
        errors=list(validator.iter_errors(row['body']))
        if errors:failures.append({'path':path,'schema':schema,'error':errors[0].message})
        else:counts[schema]+=1
    result={'frontend_sha':sha,'sample':name,'total':len(events),'passed_by_schema':dict(counts),'failures':failures,'validator':'Draft202012Validator + FormatChecker; schema only, no browser'}
    (root/'artifacts'/(name+'-schema.json')).write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
    assert not failures