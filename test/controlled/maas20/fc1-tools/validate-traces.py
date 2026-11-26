import json
from pathlib import Path
from jsonschema import Draft202012Validator

root = Path.cwd()
contract = json.loads((root / 'docs/contracts/agent-runtime/ar1-draft2/openapi.json').read_text(encoding='utf-8'))
event_schema = json.loads((root / 'docs/contracts/agent-runtime/ar1-draft2/session-event.schema.json').read_text(encoding='utf-8'))
event_validator = Draft202012Validator(event_schema)
results = []
for name in ('complete', 'invalid_second_tool'):
    path = root / 'artifacts/fc1-wire' / (name + '.json')
    doc = json.loads(path.read_text(encoding='utf-8'))
    samples = 0
    for row in doc['http']:
        target, method = row['path'], row['method']
        schema = ('Conversation' if target == '/api/agent/v1/sessions'
                  else 'RunAccepted' if method == 'POST' and target.endswith('/runs')
                  else 'EventPage' if '/events?' in target else 'Run')
        validator = Draft202012Validator({'$ref': '#/components/schemas/' + schema, 'components': contract['components']})
        validator.validate(row['body'])
        samples += 1
    events = [event['ar1'] for event in doc['persisted_session']['events']]
    for event in events:
        event_validator.validate(event)
    expected = 2 if name == 'complete' else 1
    assert len(doc['original_child_records']) == expected
    serialized = json.dumps(doc)
    for forbidden in ('"csrf_token"', '"password"', '"authorization"', '"cookie"', '"raw_key"'):
        assert forbidden not in serialized.lower(), forbidden
    results.append({'case': name, 'http_samples': samples, 'persisted_events': len(events), 'original_children': expected, 'official_schema': 'passed'})
output = {'scope': 'actual controlled HTTP and persisted MySQL sample validation, no real supplier', 'cases': results}
(root / 'artifacts/fc1-wire/schema-validation.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(output))
