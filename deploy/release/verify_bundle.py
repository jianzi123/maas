"""Verify complete locked installer/source sets without contacting any service."""
import argparse
import hashlib
import json
from pathlib import Path
from fetch_source import METADATA, source_manifest

def verify(root, source_only=False):
    root=Path(root).resolve();failures=[];manifest={};version={}
    try:
        version=json.loads((root/'VERSION.json').read_text(encoding='utf-8'))
        sources=source_manifest(root,version)
        manifest=json.loads((root/'MANIFEST.sha256.json').read_text(encoding='utf-8'))
        if not isinstance(manifest,dict) or not manifest:raise ValueError('complete installer manifest required')
        required={'source/'+name for name in sources}|{'VERSION.json','SOURCE.sha256.json'}
        if not source_only:
            kind=version.get('installer')
            if kind not in ('compose','kubernetes'):raise ValueError('installer kind missing')
            required.update(('README.md','VALIDATION.md'))
            prefix='deploy/release/'+kind+'/'
            required.update(name[len(prefix):] for name in sources if name.startswith(prefix))
            if version.get('sourceMode')=='fetch':
                required.add('fetch_source.py');required.update('metadata/'+name for name in METADATA)
        failures.extend('missing-manifest:'+name for name in sorted(required-set(manifest)))
        for name,row in sources.items():
            relative='source/'+name
            if manifest.get(relative)!=row['sha256']:failures.append('source-manifest-binding:'+name)
            path=(root/relative).resolve()
            if not path.is_relative_to(root/'source') or not path.is_file() or path.stat().st_size!=row['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
                failures.append('source-bytes:'+name)
        for name,expected in manifest.items():
            if source_only and not (name.startswith('source/') or name in ('VERSION.json','SOURCE.sha256.json')):continue
            path=(root/name).resolve()
            if not path.is_relative_to(root) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:failures.append(name)
    except (ValueError,OSError,KeyError,TypeError) as error:
        failures.append(type(error).__name__+':'+str(error))
    return {'repositoryCommit':version.get('repositoryCommit'),'codeCommit':version.get('codeCommit'),'filesChecked':len(manifest),'passed':not failures,'failures':failures}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',default='.')
    parser.add_argument('--source-only',action='store_true')
    args=parser.parse_args();result=verify(args.root,args.source_only);print(json.dumps(result));raise SystemExit(0 if result['passed'] else 1)
