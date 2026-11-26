import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('maas9_http_vectors', ROOT / 'http_tool_vectors.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class HTTPConsumerTests(unittest.TestCase):
    def cases(self):
        return {c['id']: c for c in m.oracle.load(m.oracle.DATA / 'vectors.json')['cases']}

    def feedback(self):
        return m.oracle.load(ROOT / 'http-vectors/feedback-case.json')

    def serialize(self, f):
        return m.provider_messages(f['messages'], f['call_records'], f['binding'])

    def test_actual_HTTP_second_turn_has_original_assistant_and_tool_results(self):
        with m.FixtureServer() as server:
            row = m.replay_over_http(self.cases()['TC02_interleaved_two_calls_serial_execution'], server)
        self.assertTrue(row['passed'])
        self.assertEqual(len(row['HTTP_requests']), 2)
        messages = row['HTTP_requests'][1]['request']['messages']
        self.assertEqual([x['role'] for x in messages], ['user', 'assistant', 'tool', 'tool'])
        self.assertEqual([x['tool_call_id'] for x in messages[2:]], ['call-a', 'call-b'])
        self.assertIn('猫🙂', messages[3]['content'])

    def test_unsupported_protocol_rejected_before_HTTP_attempt(self):
        with m.FixtureServer() as server:
            row = m.replay_over_http(self.cases()['TC45_text_protocol_cannot_enable_tools'], server)
            self.assertEqual(server.observations, [])
        self.assertTrue(row['passed'])
        self.assertEqual(row['result']['tool_executions'], [])

    def test_actual_clean_HTTP_EOF_without_DONE_has_no_tool_execution(self):
        with m.FixtureServer() as server:
            row = m.replay_over_http(self.cases()['TC19_EOF_before_DONE'], server)
        self.assertEqual(row['result']['status'], 'interrupted')
        self.assertEqual(row['result']['tool_executions'], [])
        self.assertIsNone(row['result']['model_usage_snapshots'][0]['usage'])

    def test_native_AR_ids_serialize_back_to_source_ids(self):
        out = self.serialize(self.feedback())
        self.assertEqual([c['id'] for c in out[0]['tool_calls']], ['source-a', 'source-b'])
        self.assertEqual([c['tool_call_id'] for c in out[1:]], ['source-a', 'source-b'])
        self.assertEqual([c['content'] for c in out[1:]], ['40', '["controlled-visible-model"]'])
        self.assertNotIn('internal-a', str(out))

    def test_foreign_and_ambiguous_mapping_rejected(self):
        f = self.feedback()
        f['call_records'][0]['source_id'] = 'foreign'
        with self.assertRaises(m.oracle.Rejected):
            self.serialize(f)
        f = self.feedback()
        f['call_records'][1]['source_call_id'] = 'source-a'
        with self.assertRaises(m.oracle.Rejected):
            self.serialize(f)

    def test_missing_unknown_or_tampered_result_cannot_be_refilled(self):
        for mutate in [lambda f: f['messages'].pop(),
                       lambda f: f['call_records'][0].update(state='unknown'),
                       lambda f: f['messages'][1]['parts'][0].update(text='changed'),
                       lambda f: f['messages'][1].update(run_id='foreign-run')]:
            f = self.feedback()
            mutate(f)
            with self.assertRaises(m.oracle.Rejected):
                self.serialize(f)

    def test_duplicate_assistant_call_does_not_collapse_to_one_result(self):
        f = self.feedback()
        f['messages'][0]['parts'].append(copy.deepcopy(f['messages'][0]['parts'][1]))
        with self.assertRaises(m.oracle.Rejected):
            self.serialize(f)

    def test_changed_arguments_invalidate_original_mapping(self):
        f = self.feedback()
        f['messages'][0]['parts'][1]['arguments']['a'] = 99
        with self.assertRaises(m.oracle.Rejected):
            self.serialize(f)

    def test_new_generation_cannot_start_with_pending_results(self):
        f = self.feedback()
        f['messages'].insert(1, {'role': 'user', 'parts': [{'type': 'text', 'text': 'continue'}]})
        with self.assertRaises(m.oracle.Rejected):
            self.serialize(f)


if __name__ == '__main__':
    unittest.main()
