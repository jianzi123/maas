import unittest
from permissions import publisher_contract, COMPLETION_SELECT, COMPLETION_UPDATE


class PublisherContractTest(unittest.TestCase):
    def template(self, select=None, update=None):
        select = ','.join(sorted(COMPLETION_SELECT)) if select is None else select
        update = ','.join(sorted(COMPLETION_UPDATE)) if update is None else update
        return (f'GRANT SELECT({select}) ON __MAAS_DATABASE__.release_management_operations TO maas_release_publisher;\n'
                f'GRANT UPDATE({update}) ON __MAAS_DATABASE__.release_management_operations TO maas_release_publisher;')

    def test_narrow_completion_columns_accepted(self):
        self.assertTrue(publisher_contract(self.template())['passed'])

    def test_missing_state_update_rejected(self):
        self.assertFalse(publisher_contract(self.template(update='reason,publication_id,updated_at'))['passed'])

    def test_action_write_rejected(self):
        self.assertFalse(publisher_contract(self.template(update=','.join(sorted(COMPLETION_UPDATE | {'action'}))))['passed'])

    def test_expected_rv_write_rejected(self):
        self.assertFalse(publisher_contract(self.template(update=','.join(sorted(COMPLETION_UPDATE | {'expected_rv'}))))['passed'])

    def test_unbounded_metadata_read_rejected(self):
        sql = self.template().replace('SELECT('+','.join(sorted(COMPLETION_SELECT))+')', 'SELECT')
        self.assertFalse(publisher_contract(sql)['passed'])

    def test_operations_role_inheritance_rejected(self):
        self.assertFalse(publisher_contract(self.template()+'GRANT maas_release_operations_runtime TO maas_release_publisher;')['passed'])

    def test_ledger_write_rejected(self):
        self.assertFalse(publisher_contract(self.template()+'GRANT UPDATE ON __MAAS_DATABASE__.usage_daily TO maas_release_publisher;')['passed'])

    def test_schema_wide_ddl_rejected(self):
        self.assertFalse(publisher_contract(self.template()+'GRANT CREATE ON __MAAS_DATABASE__.* TO maas_release_publisher;')['passed'])
