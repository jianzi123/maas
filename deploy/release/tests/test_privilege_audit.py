"""Policy/parser and fail-closed tests; live MySQL cases are in the SQL harness."""
import copy,hashlib,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
RELEASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(RELEASE))
import audit_runtime_privileges as audit
import install_compose
import install_kubernetes


def locked_policy(root):
    repo=RELEASE.parents[1];files={};backend={};deployment={}
    for name in audit.SQL_FILES:
        file=repo/'config/mysql'/name;files[name]=file
        backend['config/mysql/'+name]=hashlib.sha256(file.read_bytes()).hexdigest()
    agent=repo/'deploy/agent/session-role.sql';deployment['deploy/agent/session-role.sql']=hashlib.sha256(agent.read_bytes()).hexdigest()
    for name in ('audit_runtime_privileges.py','migrate.sh'):deployment['deploy/release/'+name]=hashlib.sha256((RELEASE/name).read_bytes()).hexdigest()
    lock={c:{'sourceCommit':'a'*40,'files':mapping} for c,mapping in (('backend',backend),('console',{}),('deployment',deployment))}
    file=root/'lock.json';file.write_text(json.dumps(lock))
    return audit.load_policy(repo/'config/mysql','maas',agent,file),file


def metadata(policy):
    rows={name:[] for name,_ in audit.queries()}
    rows['identity']=[['installer@%','maas','server-fixture','8.4.7','',0]];rows['identity_end']=copy.deepcopy(rows['identity'])
    rows['accounts']=[[name,'%']+['N']*len(audit.GLOBAL_FLAGS) for name in sorted(audit.PRINCIPALS)]
    rows['role_edges']=[[audit.RUNTIME,'%',role,'%','N'] for role in sorted(audit.ROLES)]
    rows['default_roles']=[[audit.RUNTIME,'%',role,'%'] for role in sorted(audit.ROLES)]
    tables={};columns={}
    for user,host,db,table,column,privilege in policy['grants']:
        key=(user,host,db,table)
        tables.setdefault(key,[set(),set()])
        if column:
            columns.setdefault(key+(column,),set()).add(privilege);tables[key][1].add(privilege)
        else:tables[key][0].add(privilege)
    rows['table_grants']=[list(key)+[','.join(sorted(v[0])),','.join(sorted(v[1]))] for key,v in tables.items()]
    rows['column_grants']=[list(key)+[','.join(sorted(v))] for key,v in columns.items()]
    return rows


class PrivilegeAuditTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.policy,self.lock=locked_policy(self.root);self.rows=metadata(self.policy)

    def test_exact_same_tree_policy_and_column_levels(self):
        self.assertFalse(audit.evaluate(self.policy,self.rows)['problems'])
        self.assertEqual(len([g for g in self.policy['grants'] if g[5]=='SHOWVIEW']),12)
        self.assertIn(('maas_agent_session_runtime','%','maas','agent_sessions_v1','revision','UPDATE'),self.policy['grants'])
        self.assertNotIn(('maas_agent_session_runtime','%','maas','agent_sessions_v1','','UPDATE'),self.policy['grants'])

    def test_duplicate_direct_privilege_is_rejected_not_merged_with_role(self):
        self.rows['table_grants'].append(['maas_runtime','%','maas','kernel_guard','SELECT',''])
        self.assertTrue(any(p['code']=='object_or_column_grant_not_approved' for p in audit.evaluate(self.policy,self.rows)['problems']))

    def test_column_and_role_expansion_rejected(self):
        for principal in ('maas_runtime','maas_release_reader'):
            with self.subTest(principal=principal):
                rows=copy.deepcopy(self.rows)
                if principal=='maas_runtime':rows['table_grants'].append([principal,'%','maas','retained_release_snapshots','','SELECT'])
                else:
                    row=next(x for x in rows['table_grants'] if x[0]==principal and x[3]=='retained_release_snapshots');row[5]='SELECT'
                rows['column_grants'].append([principal,'%','maas','retained_release_snapshots','spec_bytes','SELECT'])
                self.assertTrue(audit.evaluate(self.policy,rows)['problems'])

    def test_global_schema_dynamic_proxy_and_routine_are_not_usage(self):
        for scope in ('global','schema','dynamic_grants','proxy_grants','routine_grants'):
            with self.subTest(scope=scope):
                rows=copy.deepcopy(self.rows)
                if scope=='global':rows['accounts'][0][2]='Y'
                elif scope=='schema':rows['schema_grants']=[['maas_runtime','%','maas']+['Y']+['N']*(len(audit.DB_FLAGS)-1)]
                else:rows[scope]=[['maas_runtime','%','unapproved']]
                self.assertTrue(audit.evaluate(self.policy,rows)['problems'])

    def test_role_admin_default_inheritance_and_mandatory(self):
        for name in ('admin','extra_default','inherited','mandatory','host'):
            with self.subTest(name=name):
                rows=copy.deepcopy(self.rows)
                if name=='admin':rows['role_edges'][0][-1]='Y'
                elif name=='extra_default':rows['default_roles'].append(['maas_runtime','%','private_role','%'])
                elif name=='inherited':rows['role_edges'].append(['maas_kernel_runtime','%','private_role','%','N'])
                elif name=='mandatory':rows['identity'][0][4]='private_role@%';rows['identity_end']=copy.deepcopy(rows['identity'])
                else:rows['accounts'].append(['maas_runtime','localhost']+['N']*len(audit.GLOBAL_FLAGS))
                self.assertTrue(audit.evaluate(self.policy,rows,allow_missing=True)['problems'])

    def test_source_lock_and_missing_privileges_fail_closed(self):
        lock=json.loads(self.lock.read_text());lock['backend']['files']['config/mysql/kernel-permissions.sql']='0'*64;self.lock.write_text(json.dumps(lock))
        with self.assertRaises(audit.AuditError):audit.load_policy(RELEASE.parents[1]/'config/mysql','maas',RELEASE.parents[1]/'deploy/agent/session-role.sql',self.lock)
        self.rows['table_grants']=[];self.rows['column_grants']=[]
        self.assertTrue(audit.evaluate(self.policy,self.rows)['problems'])
        self.assertFalse(audit.evaluate(self.policy,self.rows,allow_missing=True)['problems'])

    def test_grant_option_and_partial_column_metadata_refused(self):
        self.rows['table_grants'][0][4]+=',Grant'
        self.assertTrue(audit.evaluate(self.policy,self.rows)['problems'])
        self.rows=metadata(self.policy);self.rows['column_grants'].pop()
        self.assertTrue(audit.evaluate(self.policy,self.rows)['problems'])
        self.rows['column_grants']=[]
        with self.assertRaises(audit.AuditError):audit.evaluate(self.policy,self.rows)

    def test_identity_change_and_wrong_database_refused(self):
        self.rows['identity_end'][0][2]='another-server'
        with self.assertRaises(audit.AuditError):audit.evaluate(self.policy,self.rows)
        self.rows=metadata(self.policy);self.rows['identity'][0][1]='other';self.rows['identity_end']=copy.deepcopy(self.rows['identity'])
        with self.assertRaises(audit.AuditError):audit.evaluate(self.policy,self.rows)

    def test_connection_denied_never_parses_partial_output(self):
        partial=json.dumps(['identity','installer@%','maas','uuid','8.4.7','',0]).encode()
        result=subprocess.CompletedProcess([],1,partial,b'ERROR 1142 (42000) at line 3: denied')
        with patch.object(audit.subprocess,'run',return_value=result):
            with self.assertRaises(audit.AuditError) as failure:audit.MysqlClient('credential-file','maas').collect(audit.queries())
        self.assertEqual(failure.exception.facts['scope'],'accounts')
        self.assertEqual(failure.exception.facts['mysqlError'],1142)

    def test_current_user_proxy_and_extra_host_role_refused(self):
        valid=['maas_runtime@%','maas','server-fixture',','.join('`'+r+'`@`%`' for r in sorted(audit.ROLES)),None,'8.4.7']
        class Client:
            def collect(self,statements):return {'runtime':[row]}
        for what in ('normal','host','proxy','hidden_host_role'):
            row=copy.deepcopy(valid)
            if what=='host':row[0]='maas_runtime@localhost'
            elif what=='proxy':row[4]='proxy@%'
            elif what=='hidden_host_role':row[3]+=',`private_role`@`localhost`'
            if what=='normal':self.assertEqual(audit.authenticate_runtime(Client(),audit.evaluate(self.policy,self.rows))['currentUser'],'maas_runtime@%')
            else:
                with self.assertRaises(audit.AuditError):audit.authenticate_runtime(Client(),audit.evaluate(self.policy,self.rows))

    def test_client_dsn_binding_and_no_include_or_login_bypass(self):
        file=self.root/'runtime.cnf';file.write_text('[client]\nhost=127.0.0.1\nuser=maas_runtime\npassword=fixture-pass\nprotocol=tcp\n');file.chmod(0o600)
        dsn=self.root/'runtime.dsn';dsn.write_text('maas_runtime:fixture-pass@tcp(127.0.0.1:3306)/maas?parseTime=true&loc=UTC')
        self.assertEqual(audit.bind_dsn(dsn,audit.client_file(file),'maas',runtime=True),'DISABLED')
        dsn.write_text('maas_runtime:other@tcp(127.0.0.1:3306)/maas')
        with self.assertRaises(audit.AuditError):audit.bind_dsn(dsn,audit.client_file(file),'maas',runtime=True)
        file.write_text('[client]\nhost=127.0.0.1\nuser=maas_runtime\npassword=fixture-pass\ninit-command=SET ROLE ALL\n')
        with self.assertRaises(audit.AuditError):audit.client_file(file)

    def test_compose_audit_failure_never_starts_candidate(self):
        commands=[]
        def execute(args,capture=False):
            commands.append(args)
            if capture:return '{"services":{"migrate":{},"maas":{},"web":{}}}'
            if 'run' in args:raise RuntimeError('audit failed')
        with self.assertRaises(RuntimeError):install_compose.install(['docker','compose'],execute)
        self.assertEqual(commands[-1][-4:],['run','--rm','--no-deps','migrate'])
        self.assertFalse(any('up' in args for args in commands))

    def native_files(self):
        for name,kind in (('namespace','Namespace'),('config','ConfigMap'),('migration','Job'),('application','Deployment')):
            doc={'apiVersion':'v1','kind':kind,'metadata':{'name':'maas' if kind=='Namespace' else 'fixture','namespace':'maas'},'spec':{}}
            (self.root/(name+'.yaml')).write_text(json.dumps(doc))

    def test_native_old_complete_does_not_bypass_new_failed_audit(self):
        self.native_files();commands=[];submitted=[]
        old={'spec':{'template':{'metadata':{'labels':{'app':'maas-migrate'}}}},'status':{'conditions':[{'type':'Complete','status':'True'}]}}
        def execute(args,capture=False,data=None):
            commands.append(args)
            if args[:2]==['get','deployment']:return 'deployment/maas'
            if args[:2]==['get','jobs']:return json.dumps({'items':[old]})
            if args==['create','-f','-']:submitted.append(json.loads(json.dumps(__import__('yaml').safe_load(data)))['metadata']['name'])
            if args[:2]==['wait','--for=condition=complete']:raise RuntimeError('new audit failed')
            return ''
        with self.assertRaises(RuntimeError):install_kubernetes.install(self.root,'maas',execute,True)
        self.assertEqual(len(submitted),1);self.assertNotEqual(submitted[0],'fixture')
        self.assertFalse(any('application.yaml' in str(a) for a in commands))

    def test_native_wrong_namespace_refused_before_api_writes(self):
        self.native_files();calls=[]
        with self.assertRaises(ValueError):install_kubernetes.install(self.root,'other',lambda *a,**k:calls.append(a),True)
        self.assertFalse(calls)


if __name__=='__main__':unittest.main()
