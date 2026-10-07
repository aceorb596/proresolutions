import uuid
from unittest.mock import Mock

import pytest
import requests

from backend.app import create_app, dispatch_one, quote_details, validate, clickup_payload


@pytest.fixture
def payload():
    return dict(name='Test Property Manager', email='test@example.com', locations='TEST — American Fork',
                notes='Synthetic test; do not contact.', offer='buildings', quantity=5,
                bird=True, timing='Planning ahead', website='')


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('ALLOWED_ORIGINS', 'https://pro-solutions-website.onrender.com')
    monkeypatch.setenv('ADMIN_TOKEN', 'local-test-only')
    store = Mock()
    store.save.side_effect = lambda key, data: ({'id': key, 'payload': data}, True)
    return create_app(store=store, clickup=Mock()).test_client(), store


def submit(client, payload, **headers):
    return client.post('/api/quotes', json=payload,
                       headers={'Idempotency-Key': str(uuid.uuid4()), **headers})


def test_server_pricing_and_five_building_boundary(client, payload):
    c, store = client
    payload['subtotal'] = 1  # Browser pricing is never trusted.
    response = submit(c, payload)
    assert response.status_code == 201
    assert response.json['subtotal'] == 6250
    assert response.json['bird_discount_eligible'] is True
    assert 'subtotal' not in store.save.call_args.args[1]
    payload['quantity'] = 4
    assert submit(c, payload).status_code == 400
    assert store.save.call_count == 1


@pytest.mark.parametrize('field,value', [('quantity', True), ('quantity', 1.5), ('quantity', 501),
                                      ('email', 'bad'), ('name', ''), ('bird', 'yes'),
                                      ('timing', 'unknown'), ('website', 'spam')])
def test_invalid_requests_never_reach_storage(client, payload, field, value):
    c, store = client
    payload[field] = value
    assert submit(c, payload).status_code == 400
    store.save.assert_not_called()


def test_stairwell_rate_and_bird_scope(payload):
    payload.update(offer='stairs', quantity=5)
    assert quote_details(validate(payload)) == dict(rate=125, subtotal=625, unit='stairwell clean', bird_discount_eligible=False)


def test_storage_failure_does_not_confirm_receipt(client, payload):
    c, store = client
    store.save.side_effect = RuntimeError('PRIVATE CONNECTION DATA')
    response = submit(c, payload)
    assert response.status_code == 503
    assert 'received' not in response.json
    assert 'PRIVATE' not in response.text


def test_replayed_receipt(client, payload):
    c, store = client
    key = str(uuid.uuid4())
    store.save.side_effect = None
    store.save.return_value = ({'id': key}, False)
    response = submit(c, payload, **{'Idempotency-Key': key})
    assert response.status_code == 200 and response.json['request_id'] == key


def test_origin_auth_and_body_limits(client, payload):
    c, store = client
    assert submit(c, payload, Origin='https://unrelated.example').status_code == 403
    assert c.get('/api/admin/quotes').status_code == 401
    store.recent.return_value = []
    assert c.get('/api/admin/quotes', headers={'Authorization': 'Bearer local-test-only'}).status_code == 200
    assert submit(c, {**payload, 'notes': 'x' * 20000}).status_code == 413
    preflight = c.options('/api/quotes', headers={'Origin':'https://pro-solutions-website.onrender.com'})
    assert preflight.status_code == 204
    assert preflight.headers['Access-Control-Allow-Origin'] == 'https://pro-solutions-website.onrender.com'


def test_successful_handoff_records_task_id(payload):
    store, clickup = Mock(), Mock()
    row = {'id': str(uuid.uuid4()), 'payload': payload, 'delivery': 'pending'}
    store.claim.return_value = row
    clickup.create.return_value = Mock(status_code=200, json=lambda: {'id':'task-test'})
    assert dispatch_one(store, clickup)
    store.finish.assert_called_once_with(row['id'], 'sent', 'task-test')
    task = clickup_payload(row)
    assert task['name'].startswith(f"[PR {row['id']}]")
    assert '$6,250' in task['description'] and '[ae-generated]' in task['description']


def test_timeout_never_blindly_resends(payload):
    store, clickup = Mock(), Mock()
    row = {'id': str(uuid.uuid4()), 'payload': payload, 'delivery': 'pending'}
    store.claim.return_value = row
    clickup.create.side_effect = requests.Timeout()
    dispatch_one(store, clickup)
    store.finish.assert_not_called()  # Persisted sending lease remains for reconciliation.
    row['delivery'] = 'sending'
    clickup.find.return_value = 'already-created'
    dispatch_one(store, clickup)
    assert clickup.create.call_count == 1
    store.finish.assert_called_once_with(row['id'], 'sent', 'already-created', None)


def test_missing_task_after_uncertain_write_requires_review(payload):
    store, clickup = Mock(), Mock()
    row = {'id': str(uuid.uuid4()), 'payload': payload, 'delivery': 'sending'}
    store.claim.return_value = row
    clickup.find.return_value = None
    dispatch_one(store, clickup)
    clickup.create.assert_not_called()
    assert store.finish.call_args.args[1] == 'needs_review'


def test_rate_limit_is_queued_for_later(payload):
    store, clickup = Mock(), Mock()
    store.claim.return_value = {'id':'test', 'payload':payload, 'delivery':'pending'}
    clickup.create.return_value = Mock(status_code=429)
    dispatch_one(store, clickup)
    assert store.finish.call_args.args[1] == 'pending'


def test_missing_configuration_fails_closed(monkeypatch, payload):
    for key in ['DATABASE_URL', 'CLICKUP_TOKEN', 'CLICKUP_LIST_ID']:
        monkeypatch.delenv(key, raising=False)
    c = create_app().test_client()
    assert c.get('/ready').status_code == 503
    assert submit(c, payload).status_code == 503
