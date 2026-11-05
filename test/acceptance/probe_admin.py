"""Read-only local admin API acceptance entry; requires real session and IDs."""
import argparse,json,os,pathlib,sys,urllib.error,urllib.parse,urllib.request
p=argparse.ArgumentParser()
p.add_argument('--base-url',required=True)
p.add_argument('--request-id',required=True,help='Previously received server generation request ID')
p.add_argument('--namespace',required=True);p.add_argument('--name',required=True)
p.add_argument('--cr-uid',required=True,help='Original server-issued CR UID')
p.add_argument('--output',type=pathlib.Path,required=True)
a=p.parse_args()
u=urllib.parse.urlsplit(a.base_url)
if u.scheme not in ['http','https'] or u.hostname not in ['localhost','127.0.0.1','::1'] or u.username or u.query or u.fragment:
    p.error('Use an authorized loopback admin API URL')
cookie=os.environ.get('MAAS_QA_ADMIN_COOKIE')
if not cookie:p.error('Set MAAS_QA_ADMIN_COOKIE through the approved local secret channel; never store it in a result file')
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kw): return None
opener=urllib.request.build_opener(NoRedirect)
results=[]
def call(name,path,query,expected,authenticated=True,verify=None):
    headers={'Accept':'application/json'}
    if authenticated:headers['Cookie']=cookie
    request=urllib.request.Request(a.base_url.rstrip('/')+path+'?'+urllib.parse.urlencode(query),headers=headers,method='GET')
    try:
        with opener.open(request,timeout=10) as response:code=response.status;raw=response.read(2**20)
    except urllib.error.HTTPError as e:code=e.code;raw=e.read(2**20)
    except (OSError,urllib.error.URLError):
        results.append({'name':name,'passed':False,'error':'connection_unavailable'});return
    ok=code==expected
    if ok and verify:
        try:ok=verify(json.loads(raw))
        except (ValueError,KeyError,TypeError):ok=False
    results.append({'name':name,'status':code,'expected_status':expected,'passed':bool(ok)})
qpath='/api/admin/v1/usage/requests'
def exact(v):
    return (v['lookup']['request_id']==a.request_id and v['lookup']['resolution']=='recorded'
            and len(v['data'])==1 and v['data'][0]['request_id']==a.request_id and v['next_cursor'] is None)
call('FE-R03 original ID across date defaults',qpath,{'request_id':a.request_id},200,verify=exact)
call('FE-R03 rejects explicit list default',qpath,{'request_id':a.request_id,'page_size':'20'},400)
call('FE-R03 rejects malformed ID',qpath,{'request_id':'invalid'},400)
call('FE-R03 anonymous denied',qpath,{'request_id':a.request_id},401,authenticated=False)
history='/api/admin/v1/model-releases/'+urllib.parse.quote(a.namespace,safe='')+'/'+urllib.parse.quote(a.name,safe='')+'/revisions'
def retained(v):
    return v['requested_cr_uid']==a.cr_uid and all(r['cr_uid']==a.cr_uid for r in v['data']) and all(
        r['rollback_eligibility']['state']!='eligible' for r in v['data']
        if v['resource_state'] in ['deleted','replaced','deleting','unknown'])
call('FE-R02 exact original UID history',history,{'cr_uid':a.cr_uid},200,verify=retained)
call('FE-R02 required original UID',history,{},400)
call('FE-R02 pagination lower bound',history,{'cr_uid':a.cr_uid,'page_size':'0'},400)
report={'kind':'read_only_local_http_acceptance','tests':results,'passed':sum(x['passed'] for x in results),
'failed':sum(not x['passed'] for x in results),'limitations':['No management writes or generation calls','503/fault injection and permission-scoped 403/404 require separate authorized fixtures','Cookie and response bodies deliberately omitted']}
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'passed':report['passed'],'failed':report['failed']}))
sys.exit(bool(report['failed']))
