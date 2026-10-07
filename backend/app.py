"""Quote intake. All customer data stays in Postgres or the configured ClickUp list."""
import hashlib
import hmac
import json
import logging
import os
import re
import threading
import uuid
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import requests
from flask import Flask, abort, jsonify, request, send_from_directory

LOG = logging.getLogger(__name__)
TIMINGS = {'Flexible — let’s discuss', 'As soon as available', 'Within the next month', 'Planning ahead'}
SITE_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ASSETS = {'app.js': 'text/javascript', 'style.css': 'text/css', 'mark.svg': 'image/svg+xml'}


def validate(data):
    if not isinstance(data, dict):
        raise ValueError('Please check your request details.')
    if data.get('website'):
        raise ValueError('Unable to accept this request.')
    clean = {}
    for field, limit in [('name', 100), ('email', 200), ('locations', 2000), ('notes', 3000)]:
        value = data.get(field, '')
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f'Please check {field}.')
        clean[field] = value.strip()
        if field != 'notes' and not clean[field]:
            raise ValueError(f'Please enter {field}.')
    clean['email'] = clean['email'].lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', clean['email']):
        raise ValueError('Please enter a valid email address.')
    offer, quantity = data.get('offer'), data.get('quantity')
    if offer not in ('stairs', 'buildings') or type(quantity) is not int:
        raise ValueError('Please check the service and quantity.')
    if not (5 if offer == 'buildings' else 1) <= quantity <= 500:
        raise ValueError('Building bundles need 5–500 buildings; stairwell requests need 1–500 cleans.')
    if data.get('timing') not in TIMINGS or type(data.get('bird')) is not bool:
        raise ValueError('Please check timing and bird protection.')
    clean.update(offer=offer, quantity=quantity, timing=data['timing'], bird=data['bird'])
    return clean


def quote_details(payload):
    buildings = payload['offer'] == 'buildings'
    rate = 1250 if buildings else 125
    return {'rate': rate, 'subtotal': rate * payload['quantity'],
            'unit': 'building' if buildings else 'stairwell clean',
            'bird_discount_eligible': buildings and payload['bird']}


class PostgresStore:
    def __init__(self, url):
        self.url = url
        with self.connect() as conn:
            conn.execute(Path(__file__).with_name('schema.sql').read_text())

    def connect(self):
        return psycopg.connect(self.url, row_factory=dict_row, connect_timeout=5,
                               options='-c statement_timeout=15000')

    def healthy(self):
        with self.connect() as conn:
            conn.execute('SELECT 1').fetchone()

    def save(self, key, payload):
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with self.connect() as conn:
            # Low-volume intake: serializes deduplication and the shared abuse limit.
            conn.execute('SELECT pg_advisory_xact_lock(72610501)')
            existing = conn.execute('SELECT * FROM pro_quote_requests WHERE id=%s', (key,)).fetchone()
            if existing:
                if existing['payload_hash'] != digest:
                    raise ValueError('This request ID already belongs to different details. Start a new request.')
                return existing, False
            counts = conn.execute("""SELECT count(*) AS total,
                count(*) FILTER (WHERE payload->>'email'=%s) AS sender
                FROM pro_quote_requests WHERE created_at > now() - interval '1 hour'""",
                (payload['email'],)).fetchone()
            if counts['total'] >= 100 or counts['sender'] >= 5:
                raise OverflowError('Too many requests. Please try again later.')
            row = conn.execute('''INSERT INTO pro_quote_requests(id,payload_hash,payload,subtotal)
                VALUES (%s,%s,%s,%s) RETURNING *''',
                (key, digest, Jsonb(payload), quote_details(payload)['subtotal'])).fetchone()
            return row, True

    def claim(self):
        with self.connect() as conn:
            row = conn.execute("""SELECT * FROM pro_quote_requests WHERE
                (delivery='pending' AND next_attempt<=now()) OR
                (delivery='sending' AND updated_at < now()-interval '3 minutes')
                ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1""").fetchone()
            if row:
                conn.execute("""UPDATE pro_quote_requests SET delivery='sending', attempts=attempts+1,
                    updated_at=now() WHERE id=%s""", (row['id'],))
            return row

    def finish(self, key, state, task_id=None, error=None, delay=60):
        with self.connect() as conn:
            conn.execute("""UPDATE pro_quote_requests SET delivery=%s, task_id=%s,
                last_error=%s, next_attempt=now()+(%s * interval '1 second'), updated_at=now()
                WHERE id=%s""", (state, task_id, error, delay, key))

    def recent(self):
        with self.connect() as conn:
            return conn.execute('SELECT * FROM pro_quote_requests ORDER BY created_at DESC LIMIT 100').fetchall()

    def set_outcome(self, key, outcome):
        with self.connect() as conn:
            return conn.execute('''UPDATE pro_quote_requests SET outcome=%s,updated_at=now()
                WHERE id=%s RETURNING id''', (outcome, key)).fetchone()


def clickup_payload(row):
    p = row['payload']
    q = quote_details(p)
    service = 'building pressure washing' if p['offer'] == 'buildings' else 'stairwell cleaning'
    next_action = 'Confirm scope and access, then prepare the quote.'
    bird_note = ('Requested; 5+ building discount, amount to confirm.' if q['bird_discount_eligible']
                 else 'Requested; separately quoted.' if p['bird'] else 'Not requested.')
    # Marker makes reconciliation exact and stops the old experimental webhook from duplicating work.
    return {'name': f"[PR {row['id']}] {p['quantity']} {service}",
            'description': f"""[ae-generated] Pro Resolutions website inquiry
Request ID: {row['id']}
Name: {p['name']}
Email: {p['email']}
Property location(s): {p['locations']}
Service: {service}
Quantity: {p['quantity']}
Indicative cleaning subtotal: ${q['subtotal']:,} (${q['rate']:,} per {q['unit']})
Bird protection: {bird_note}
Timing: {p['timing']}
Notes: {p['notes'] or 'None'}

NEXT ACTION: {next_action}
No booking or final quote has been confirmed. After sending a quote, set a follow-up date.
Track progress using ClickUp status; the API also supports new/quoted/booked/lost outcomes.
""", 'notify_all': False}


class ClickUp:
    def __init__(self, token, list_id):
        self.headers = {'Authorization': token, 'Content-Type': 'application/json'}
        self.base = f'https://api.clickup.com/api/v2/list/{list_id}/task'

    def create(self, row):
        # No automatic HTTP retries: a timeout could mean ClickUp accepted the write.
        return requests.post(self.base, headers=self.headers, json=clickup_payload(row), timeout=20)

    def find(self, key):
        marker = f'[PR {key}]'
        for page in range(100):
            response = requests.get(self.base, headers=self.headers,
                                    params={'include_closed': 'true', 'page': page}, timeout=20)
            response.raise_for_status()
            tasks = response.json().get('tasks', [])
            for task in tasks:
                if task.get('name', '').startswith(marker):
                    return task['id']
            if not tasks:
                return None
        raise RuntimeError('Reconciliation page limit reached')


def dispatch_one(store, clickup):
    row = store.claim()
    if not row:
        return False
    key = row['id']
    if row['delivery'] == 'sending':
        # Previous process stopped with an uncertain write. Reconcile without sending again.
        try:
            task_id = clickup.find(key)
            store.finish(key, 'sent' if task_id else 'needs_review', task_id,
                         None if task_id else 'Interrupted handoff; check ClickUp before retrying.')
        except Exception:
            store.finish(key, 'needs_review', error='Unable to reconcile interrupted handoff.')
        return True
    try:
        response = clickup.create(row)
        if 200 <= response.status_code < 300:
            task_id = response.json().get('id')
            if not task_id:
                raise ValueError('Missing task ID')
            store.finish(key, 'sent', str(task_id))
        elif response.status_code == 429:
            store.finish(key, 'pending', error='ClickUp rate limit', delay=300)
        else:
            store.finish(key, 'needs_review', error=f'ClickUp returned HTTP {response.status_code}; check before retrying.')
    except (requests.RequestException, ValueError):
        # Leave sending persisted. The next pass reconciles after the lease expires.
        LOG.warning('ClickUp handoff uncertain; reconciliation required (no customer details logged).')
    return True


def create_app(store=None, clickup=None, start_worker=False):
    app = Flask(__name__, static_folder=None)
    app.config['MAX_CONTENT_LENGTH'] = 16384
    origins = {x.strip().rstrip('/') for x in os.getenv('ALLOWED_ORIGINS', '').split(',') if x.strip()}
    admin = os.getenv('ADMIN_TOKEN', '')
    if store is None and os.getenv('DATABASE_URL'):
        store = PostgresStore(os.environ['DATABASE_URL'])
    if clickup is None and os.getenv('CLICKUP_TOKEN') and os.getenv('CLICKUP_LIST_ID'):
        clickup = ClickUp(os.environ['CLICKUP_TOKEN'], os.environ['CLICKUP_LIST_ID'])
    wake = threading.Event()

    @app.get('/')
    def website():
        return send_from_directory(SITE_ROOT, 'index.html')

    @app.get('/api-config.js')
    def api_config():
        # The same service serves the page and API. Missing connections retain
        # the explicit preview experience instead of suggesting a request was sent.
        value = 'window.location.origin' if store is not None and clickup is not None else "''"
        return app.response_class(f'window.PRO_RESOLUTIONS_API = {value};\n', mimetype='text/javascript')

    @app.get('/<path:asset>')
    def public_asset(asset):
        if asset not in PUBLIC_ASSETS:
            abort(404)
        return send_from_directory(SITE_ROOT, asset, mimetype=PUBLIC_ASSETS[asset])

    @app.before_request
    def guard():
        origin = request.headers.get('Origin')
        if origin and origin not in origins:
            return jsonify(error='This website is not allowed to submit here.'), 403
        if request.path.startswith('/api/admin/'):
            expected = 'Bearer ' + admin
            if not admin or not hmac.compare_digest(request.headers.get('Authorization', ''), expected):
                return jsonify(error='Unauthorized'), 401

    @app.after_request
    def response_headers(response):
        origin = request.headers.get('Origin')
        if origin in origins:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Vary'] = 'Origin'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Idempotency-Key'
            response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.errorhandler(413)
    def too_large(_):
        return jsonify(error='Please shorten your request.'), 413

    @app.errorhandler(Exception)
    def unavailable(error):
        from werkzeug.exceptions import HTTPException
        if isinstance(error, HTTPException):
            return jsonify(error=error.name), error.code
        LOG.error('Request failed: %s', type(error).__name__)
        return jsonify(error='We could not confirm receipt. Please try again with the same details.'), 503

    @app.get('/health')
    def health():
        return jsonify(ok=True)

    @app.get('/ready')
    def ready():
        if store is None or clickup is None:
            return jsonify(ready=False), 503
        store.healthy()
        return jsonify(ready=True)

    @app.route('/api/quotes', methods=['POST', 'OPTIONS'])
    def quotes():
        if request.method == 'OPTIONS':
            return '', 204
        if store is None or clickup is None:
            return jsonify(error='Quote requests are not available yet. Please try again later.'), 503
        if not request.is_json:
            return jsonify(error='Expected a JSON request.'), 415
        try:
            raw_key = request.headers.get('Idempotency-Key', '')
            key = uuid.UUID(raw_key)
            if key.version != 4:
                raise ValueError('Invalid request ID. Reload the page and try again.')
            payload = validate(request.get_json(silent=True))
            row, created = store.save(str(key), payload)
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except OverflowError as error:
            return jsonify(error=str(error)), 429
        wake.set()
        return jsonify(received=True, request_id=str(row['id']), **quote_details(payload)), 201 if created else 200

    @app.get('/api/admin/quotes')
    def admin_quotes():
        return jsonify(requests=store.recent())

    @app.patch('/api/admin/quotes/<uuid:key>')
    def outcome(key):
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict) or data.get('outcome') not in ('new', 'quoted', 'booked', 'lost'):
            return jsonify(error='Invalid outcome'), 400
        row = store.set_outcome(str(key), data['outcome'])
        return (jsonify(updated=True), 200) if row else (jsonify(error='Not found'), 404)

    def worker():
        while True:
            try:
                if store and clickup:
                    for _ in range(10):
                        if not dispatch_one(store, clickup):
                            break
            except Exception as error:
                LOG.error('Delivery worker failed: %s', type(error).__name__)
            wake.wait(15)
            wake.clear()

    if start_worker:
        threading.Thread(target=worker, daemon=True, name='clickup-outbox').start()
    return app


if __name__ == '__main__':
    create_app(start_worker=True).run(host='0.0.0.0', port=int(os.getenv('PORT', '10000')))
