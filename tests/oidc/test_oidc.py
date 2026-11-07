"""Real Flask application and PyOIDC protocol regression tests, no live IdP."""
import importlib.metadata
import io
import json
import os
import pickle
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

import flask
import requests
from Cryptodome.PublicKey import RSA
from jwkest.jwk import RSAKey
from oic.oic.message import IdToken
from mailu import create_app_from_config, configuration, models, oidc, utils
from mailu.internal import nginx

ISSUER = 'https://idp.example.org'
EMAIL = 'alice@example.org'


class FakeIdP:
    key = RSAKey(key=RSA.generate(2048), use='sig', kid='test-key')

    def __init__(self):
        self.calls = []
        self.nonce = None
        self.claims = {}
        self.email = EMAIL
        self.sub = 'subject-1'
        self.active = True
        self.outage = set()
        self.omit = set()
        self.rotate = False
        self.reject_refresh = False
        self.introspection = True
        self.signing_key = self.key
        self.missing_refresh = False
        self.introspection_claims = {}

    def request(self, method, url, **kwargs):
        path = urlsplit(url).path
        self.calls.append((path, kwargs))
        response = requests.Response()
        response.url = url
        response.headers['Content-Type'] = 'application/json'
        response.status_code = 200
        if path in self.outage:
            response.status_code = 503
            data = {'error': 'temporarily_unavailable'}
        elif path.endswith('/.well-known/openid-configuration'):
            data = {'issuer': ISSUER, 'authorization_endpoint': ISSUER + '/authorize',
                    'token_endpoint': ISSUER + '/token', 'userinfo_endpoint': ISSUER + '/userinfo',
                    'jwks_uri': ISSUER + '/jwks', 'response_types_supported': ['code'],
                    'subject_types_supported': ['public'], 'id_token_signing_alg_values_supported': ['RS256']}
            if self.introspection:
                data['introspection_endpoint'] = ISSUER + '/introspect'
        elif path == '/jwks':
            data = {'keys': [self.key.serialize()]}
        elif path == '/token':
            args = parse_qs(kwargs.get('data', ''))
            grant = args.get('grant_type', [''])[0]
            if grant == 'password':
                assert set(args.get('scope', [''])[0].split()) == {'openid','email','profile'}
            if grant == 'password' and args.get('password') != ['idp-password']:
                response.status_code = 400
                data = {'error': 'invalid_grant'}
            elif grant == 'refresh_token' and self.reject_refresh:
                response.status_code = 400
                data = {'error': 'invalid_grant'}
            else:
                data = {'access_token': 'access-1', 'token_type': 'Bearer', 'expires_in': 300}
                if not self.missing_refresh and (grant != 'refresh_token' or self.rotate):
                    data['refresh_token'] = 'refresh-2' if self.rotate else 'refresh-1'
                if grant == 'authorization_code':
                    now = int(time.time())
                    claims = {'iss': ISSUER, 'aud': ['mailu'], 'sub': self.sub, 'iat': now,
                              'exp': now + 300, 'nonce': self.nonce, 'auth_time': now}
                    claims.update(self.claims)
                    for key in self.omit:
                        claims.pop(key, None)
                    data['id_token'] = IdToken(**claims).to_jwt(key=[self.signing_key], algorithm='RS256')
        elif path == '/userinfo':
            data = {'sub': self.sub, 'email': self.email, 'name': 'Alice', 'email_verified': False}
        elif path == '/introspect':
            data = {'active': self.active, 'exp': int(time.time()) + 300, **self.introspection_claims}
        else:
            raise AssertionError('Unexpected provider request: ' + url)
        response._content = json.dumps(data).encode()
        return response


class TestConfig:
    def __init__(self, uri, **overrides):
        self.uri, self.overrides = uri, overrides

    def init_app(self, app):
        configuration.ConfigManager().init_app(app)
        app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=self.uri, MEMORY_SESSIONS=True,
                          RATELIMIT_STORAGE_URL='memory://', SECRET_KEY='deterministic-test-key',
                          CREDENTIAL_ROUNDS=4, OIDC_ENABLED=True, OIDC_PROVIDER_INFO_URL=ISSUER,
                          OIDC_REDIRECT_HOST='mail.example.org', API_TOKEN='', ADMIN=True,
                          SESSION_COOKIE_SECURE=False, WTF_CSRF_ENABLED=True)
        app.config.update(self.overrides)


class OidcTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.config = TestConfig('sqlite:///' + self.directory.name + '/mailu.db')
        self.app = create_app_from_config(self.config)
        self.ctx = self.app.app_context(); self.ctx.push()
        models.db.create_all()
        models.Base.metadata.create_all(models.db.engine)
        domain = models.Domain(name='example.org', max_users=3, max_quota_bytes=500000)
        user = models.User(domain=domain, localpart='alice', password='openid')
        user.set_password('local-password')
        models.db.session.add_all([domain, user]); models.db.session.commit()
        self.client = self.app.test_client()
        self.idp = FakeIdP()
        self.transport = patch('requests.sessions.Session.request', autospec=True, side_effect=lambda session, method, url, **kwargs: self.idp.request(method, url, **kwargs)); self.transport.start()
        # Avoid unrelated DNS/network lookups in Mailu's country exemption checks.
        self.geo = patch('mailu.utils.is_suspicious_country_ip', return_value=False); self.geo.start()

    def tearDown(self):
        self.geo.stop(); self.transport.stop()
        models.db.session.remove(); models.db.drop_all(); self.ctx.pop(); self.directory.cleanup()

    def user(self):
        return models.User.get(EMAIL)

    def begin(self, client=None):
        client = client or self.client
        response = client.get('/sso/oidc/start')
        self.assertEqual(response.status_code, 302)
        args = parse_qs(urlsplit(response.location).query)
        self.assertIn('state', args, response.location)
        self.idp.nonce = args['nonce'][0]
        return args

    def callback(self, args, client=None, **changes):
        return (client or self.client).get('/sso/login/oidc?' + urlencode({'code': 'valid-code', 'state': args['state'][0], **changes}))

    def login(self):
        response = self.callback(self.begin())
        self.assertEqual(response.location, '/admin')
        return response

    def csrf(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.data[:500])
        match = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', response.data)
        self.assertIsNotNone(match, response.data[:1000])
        return match[1].decode()

    def passwordless(self):
        self.user().password = 'openid'; models.db.session.commit()

    def reauthenticate(self, operation='token', target=EMAIL):
        path = '/sso/oidc/reauthenticate?' + urlencode({'operation': operation, 'target': target})
        csrf = self.csrf(path)
        response = self.client.post(path, data={'csrf_token': csrf})
        args = parse_qs(urlsplit(response.location).query)
        self.assertEqual(args['prompt'], ['login']); self.assertEqual(args['max_age'], ['0'])
        self.idp.nonce = args['nonce'][0]
        return self.callback(args)

    def test_library_version_and_pins(self):
        self.assertEqual(importlib.metadata.version('oic'), '1.7.0')
        for path in ['/tests/dependencies/requirements-prod.txt', '/tests/dependencies/requirements-dev.txt', '/tests/oidc/requirements.txt']:
            self.assertIn('oic==1.7.0', Path(path).read_text().splitlines())

    def test_local_first_and_session_cannot_authenticate_password(self):
        self.login(); self.idp.calls.clear()
        with self.app.test_request_context():
            flask.session['oidc_token'] = {'access_token': 'not-a-password'}
            self.assertTrue(self.user().check_password('local-password'))
            self.assertFalse(self.idp.calls)
            self.assertFalse(self.user().check_password('wrong'))
            self.assertTrue(self.user().check_password('idp-password'))
            self.assertNotIn('auth_origin', flask.session)
        self.assertTrue(any(path == '/token' for path, _ in self.idp.calls))

    def test_oidc_disabled_local_and_passwordless_idp(self):
        self.app.config['OIDC_ENABLED'] = False
        with self.app.test_request_context():
            self.assertTrue(self.user().check_password('local-password'))
            self.assertFalse(self.user().check_password('idp-password'))
        self.app.config['OIDC_ENABLED'] = True; self.passwordless()
        with self.app.test_request_context():
            self.assertTrue(self.user().check_password('idp-password'))
            self.assertNotIn('oidc_token', flask.session)

    def test_callback_and_introspection_real_library(self):
        self.idp.email = 'ALICE@EXAMPLE.ORG'
        self.login()
        self.assertEqual(self.user().displayed_name, 'Alice')
        response = self.client.get('/internal/auth/user')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['X-User'], EMAIL)
        self.assertTrue(response.headers['X-User-Token'].startswith('token-'))
        self.assertTrue(any(p == '/introspect' for p, _ in self.idp.calls))

    def test_callback_replay_cross_session_cancel_and_missing_state(self):
        args = self.begin()
        other = self.app.test_client()
        self.assertEqual(self.callback(args, other).location, '/sso/login')
        self.assertEqual(self.callback(args).location, '/admin')
        self.assertEqual(self.callback(args).location, '/sso/login')
        self.assertEqual(self.client.get('/sso/login/oidc').location, '/sso/login')
        args = self.begin()
        self.assertEqual(self.callback(args, error='access_denied').location, '/sso/login')

    def test_protocol_nonce_issuer_audience_expiry_and_missing_claims(self):
        for claims, omit in [({'nonce':'wrong'},set()), ({'iss':'https://wrong.test'},set()),
                             ({'aud':['other-client']},set()), ({'exp':int(time.time())-60},set()), ({}, {'sub'}), ({}, {'nonce'})]:
            with self.subTest(claims=claims, omit=omit):
                self.idp.claims, self.idp.omit = claims, omit
                response = self.callback(self.begin())
                self.assertEqual(response.location, '/sso/login')
                with self.client.session_transaction() as s: self.assertNotIn('_user_id', s)
        self.idp.claims = {}; self.idp.omit = set()
        args = self.begin(); self.idp.claims['sub'] = 'different'
        self.assertEqual(self.callback(args).location, '/sso/login')

    def test_worker_restart_does_not_lose_transaction(self):
        args = self.begin()
        self.app.extensions['mailu_oidc']['provider'] = None
        self.assertEqual(self.callback(args).location, '/admin')

    def test_disabled_and_deleted_session_next_request(self):
        self.login(); self.user().enabled = False; models.db.session.commit()
        self.assertEqual(self.client.get('/internal/auth/user').status_code, 403)
        with self.client.session_transaction() as s: self.assertNotIn('_user_id', s)
        self.user().enabled = True; models.db.session.commit(); self.login()
        models.db.session.delete(self.user()); models.db.session.commit()
        self.assertEqual(self.client.get('/admin/').status_code, 403)

    def test_disabled_new_oidc_and_application_tokens(self):
        self.user().enabled = False; models.db.session.commit()
        self.assertEqual(self.callback(self.begin()).location, '/sso/login')
        with self.app.test_request_context():
            self.assertFalse(nginx.check_credentials(self.user(), 'local-password', '127.0.0.1', 'smtp'))

    def test_introspection_cache_revocation_zero_ttl(self):
        self.login(); self.assertEqual(self.client.get('/internal/auth/user').status_code, 200)
        self.idp.active = False
        self.assertEqual(self.client.get('/internal/auth/user').status_code, 200)
        with self.client.session_transaction() as s: s['oidc_token'] = {**s['oidc_token'], 'checked_until': 0}
        self.assertEqual(self.client.get('/internal/auth/user').status_code, 403)
        self.assertFalse(any('refresh_token' in kwargs.get('data', '') for p, kwargs in self.idp.calls if p == '/token'))
        self.idp.active = True; self.app.config['OIDC_INTROSPECTION_CACHE_TTL'] = 0
        self.login(); self.client.get('/admin/')
        self.idp.active = False
        self.assertEqual(self.client.get('/admin/').status_code, 403)

    def test_outage_retains_session_and_local_login_recovers(self):
        self.login(); self.idp.outage.add('/introspect')
        self.assertEqual(self.client.get('/admin/').status_code, 503)
        self.assertEqual(self.client.get('/internal/auth/user').status_code, 403)
        with self.client.session_transaction() as s: self.assertIn('oidc_token', s)
        self.assertEqual(self.client.get('/sso/login').status_code, 200)
        response = self.client.post('/sso/login', data={'email':EMAIL,'pw':'local-password','submitAdmin':'Sign in'})
        self.assertEqual(response.location, '/admin')
        with self.client.session_transaction() as s:
            self.assertEqual(s['auth_origin'],'local'); self.assertNotIn('oidc_token',s)
        self.assertEqual(self.client.get('/admin/').status_code, 302)

    def test_discovery_recovery_and_missing_introspection(self):
        self.idp.outage.add('/.well-known/openid-configuration')
        self.assertEqual(self.client.get('/sso/oidc/start').location, '/sso/login')
        self.assertTrue(self.app.config['OIDC_ENABLED'])
        count = len(self.idp.calls)
        self.client.get('/sso/oidc/start'); self.assertEqual(len(self.idp.calls), count)
        self.idp.outage.clear(); self.app.extensions['mailu_oidc']['retry_at'] = 0
        self.login()
        self.app.extensions['mailu_oidc']['provider'] = None; self.idp.introspection = False
        self.assertEqual(self.client.get('/sso/oidc/start').location, '/sso/login')

    def test_refresh_rotation_nonrotation_rejection_and_outage(self):
        for rotate in (False, True):
            self.idp.rotate = False; self.login(); self.idp.rotate = rotate
            with self.client.session_transaction() as s: s['oidc_token'] = {**s['oidc_token'], 'expires_at':0}
            self.assertEqual(self.client.get('/internal/auth/user').status_code, 200)
            with self.client.session_transaction() as s:
                self.assertEqual(s['oidc_token']['refresh_token'], 'refresh-2' if rotate else 'refresh-1')
        with self.client.session_transaction() as s: s['oidc_token'] = {**s['oidc_token'], 'expires_at':0}
        self.idp.outage.add('/token')
        self.assertEqual(self.client.get('/admin/').status_code, 503)
        with self.client.session_transaction() as s: self.assertIn('oidc_token',s)
        self.idp.outage.clear(); self.idp.reject_refresh = True
        self.assertEqual(self.client.get('/admin/').status_code, 403)

    def test_provision_existing_domain_limits_privileges_no_password(self):
        self.app.config['OIDC_AUTH_CREATE'] = True
        self.idp.email = 'new@example.org'; self.assertEqual(self.callback(self.begin()).location, '/admin')
        user = models.User.get(self.idp.email)
        self.assertFalse(user.global_admin); self.assertFalse(user.has_local_password)
        self.assertEqual(user.quota_bytes, 500000)
        self.client.get('/sso/logout')
        domain = models.Domain.query.get('example.org'); domain.max_users = 2; models.db.session.commit()
        self.idp.email = 'third@example.org'; self.assertEqual(self.callback(self.begin()).location, '/sso/login')
        self.assertIsNone(models.User.get(self.idp.email))
        self.idp.email = EMAIL; self.login()  # existing users work at capacity

    def test_provision_default_off_unknown_domain_no_mail_provision(self):
        self.idp.email = 'new@example.org'
        self.assertEqual(self.callback(self.begin()).location, '/sso/login')
        self.assertIsNone(models.User.get(self.idp.email))
        self.app.config['OIDC_AUTH_CREATE'] = True; self.idp.email = 'new@unknown.test'
        self.assertEqual(self.callback(self.begin()).location, '/sso/login')
        self.assertIsNone(models.Domain.query.get('unknown.test'))

    def test_token_post_requires_local_password_or_fresh_one_use_proof(self):
        self.login(); csrf = self.csrf('/admin/token/create')
        data = {'csrf_token':csrf, 'raw_password':'a'*32, 'comment':'test'}
        self.client.post('/admin/token/create', data=data)
        self.assertEqual(len(self.user().tokens), 0)
        data['current_pw']='local-password'; self.client.post('/admin/token/create', data=data)
        self.assertEqual(len(self.user().tokens), 1)
        self.passwordless(); self.reauthenticate()
        csrf = self.csrf('/admin/token/create'); data.update(csrf_token=csrf, current_pw='', raw_password='b'*32)
        self.client.post('/admin/token/create', data=data); self.assertEqual(len(self.user().tokens),2)
        data['raw_password']='c'*32; self.client.post('/admin/token/create', data=data)
        self.assertEqual(len(self.user().tokens),2)

    def test_proof_wrong_operation_stale_account_and_csrf(self):
        self.login(); self.passwordless(); self.reauthenticate()
        csrf = self.csrf('/admin/user/password')
        self.client.post('/admin/user/password', data={'csrf_token':csrf, 'pw':'new-local-password', 'pw2':'new-local-password'})
        self.assertFalse(self.user().has_local_password)
        self.client.post('/admin/token/create', data={'raw_password':'a'*32})
        self.assertEqual(len(self.user().tokens),0)
        with self.client.session_transaction() as s:
            key=s['oidc_proof']; value=pickle.loads(self.app.session_store.get(key));value['until']=0
            self.app.session_store.put(key,pickle.dumps(value),120)
        csrf=self.csrf('/admin/token/create')
        self.client.post('/admin/token/create',data={'csrf_token':csrf,'raw_password':'a'*32})
        self.assertEqual(len(self.user().tokens),0)

    def test_initial_password_fresh_oidc_and_later_local_password(self):
        self.login(); self.passwordless(); self.reauthenticate('password')
        csrf=self.csrf('/admin/user/password')
        self.client.post('/admin/user/password',data={'csrf_token':csrf,'pw':'new-local-password','pw2':'new-local-password'})
        self.assertTrue(self.user().check_password_internal('new-local-password'))
        csrf=self.csrf('/admin/user/password')
        self.client.post('/admin/user/password',data={'csrf_token':csrf,'current_pw':'new-local-password','pw':'another-password','pw2':'another-password'})
        self.assertTrue(self.user().check_password_internal('another-password'))

    def test_stale_auth_time_and_wrong_actor_reauthentication(self):
        self.login()
        for claims in ({'auth_time':int(time.time())-600}, {'sub':'wrong-subject'}):
            self.idp.claims=claims
            self.assertEqual(self.reauthenticate().location,'/sso/login')
            with self.client.session_transaction() as s:self.assertNotIn('oidc_proof',s)

    def test_smtp_tokens_protocol_policies_and_session_independence(self):
        self.login(); self.passwordless()
        with self.app.test_request_context():
            flask.session['oidc_token']={'arbitrary':'browser-only'}
            self.assertFalse(nginx.check_credentials(self.user(),'wrong','127.0.0.1','smtp'))
            self.assertTrue(nginx.check_credentials(self.user(),'idp-password','127.0.0.1','smtp'))
            self.app.config['AUTH_REQUIRE_TOKENS']=True
            self.assertFalse(nginx.check_credentials(self.user(),'idp-password','127.0.0.1','smtp'))
            token=models.Token(user=self.user(),ip=['127.0.0.1/32']);token.set_password('a'*32)
            models.db.session.add(token);models.db.session.commit()
            self.assertTrue(nginx.check_credentials(self.user(),'a'*32,'127.0.0.1','smtp'))
            self.assertFalse(nginx.check_credentials(self.user(),'a'*32,'192.0.2.1','smtp'))
            self.user().enable_imap=False
            self.assertFalse(nginx.check_credentials(self.user(),'a'*32,'127.0.0.1','imap'))

    def test_logout_keeps_idp_and_application_tokens(self):
        self.login(); csrf=self.csrf('/admin/token/create')
        self.client.post('/admin/token/create',data={'csrf_token':csrf,'current_pw':'local-password','raw_password':'a'*32})
        self.idp.calls.clear(); response=self.client.get('/sso/logout')
        self.assertEqual(response.location,'/sso/login');self.assertFalse(self.idp.calls)
        self.assertEqual(len(self.user().tokens),1)
        with self.client.session_transaction() as s:self.assertNotIn('_user_id',s);self.assertNotIn('oidc_token',s)
        self.assertIn('roundcube_sessid=empty',str(response.headers))


    def test_bad_signature_missing_refresh_and_introspection_identity(self):
        self.idp.signing_key = RSAKey(key=RSA.generate(2048), use='sig', kid='wrong-key')
        self.assertEqual(self.callback(self.begin()).location, '/sso/login')
        self.idp.signing_key = self.idp.key; self.idp.missing_refresh = True; self.login()
        with self.client.session_transaction() as s: s['oidc_token'] = {**s['oidc_token'], 'expires_at':0}
        self.assertEqual(self.client.get('/admin/').status_code,403)
        self.idp.missing_refresh = False; self.login(); self.idp.introspection_claims={'sub':'wrong-sub'}
        self.assertEqual(self.client.get('/admin/').status_code,403)

    def test_second_application_worker_callback_and_refresh(self):
        args=self.begin()
        other_app=create_app_from_config(self.config)
        other_app.session_store=self.app.session_store
        other=other_app.test_client()
        cookie=self.client.get_cookie(self.app.config['SESSION_COOKIE_NAME'])
        other.set_cookie(cookie.key,cookie.value)
        self.assertEqual(self.callback(args,other).location,'/admin')
        with other.session_transaction() as s:s['oidc_token']={**s['oidc_token'],'expires_at':0}
        self.assertEqual(other.get('/internal/auth/user').status_code,200)

    def test_forced_password_post_cannot_bypass_fresh_verification(self):
        self.user().change_pw_next_login=True;models.db.session.commit()
        response=self.callback(self.begin());self.assertEqual(response.location,'/sso/pw_change')
        self.passwordless();csrf=self.csrf('/sso/pw_change')
        data={'csrf_token':csrf,'pw':'initial-password','pw2':'initial-password'}
        self.client.post('/sso/pw_change',data=data);self.assertFalse(self.user().has_local_password)
        self.reauthenticate('forced_password');data['csrf_token']=self.csrf('/sso/pw_change')
        self.assertEqual(self.client.post('/sso/pw_change',data=data).location,'/admin')
        self.assertTrue(self.user().check_password_internal('initial-password'))
        self.assertFalse(self.user().change_pw_next_login)

    def test_delegated_token_verifies_actor_and_admin_password_rights(self):
        actor=self.user();actor.global_admin=True
        target=models.User(domain=actor.domain,localpart='bob',password='openid')
        target.set_password('target-password');models.db.session.add(target);models.db.session.commit()
        self.login();path='/admin/token/create/bob@example.org';csrf=self.csrf(path)
        data={'csrf_token':csrf,'raw_password':'a'*32,'current_pw':'target-password'}
        self.client.post(path,data=data);self.assertEqual(len(target.tokens),0)
        data['current_pw']='local-password';self.client.post(path,data=data);self.assertEqual(len(target.tokens),1)
        path='/admin/user/password/bob@example.org';csrf=self.csrf(path)
        self.client.post(path,data={'csrf_token':csrf,'pw':'admin-new-password','pw2':'admin-new-password'})
        self.assertTrue(target.check_password_internal('admin-new-password'))

    def test_new_reauthentication_invalidates_old_proof_and_csrf_start(self):
        self.login();self.reauthenticate()
        path='/sso/oidc/reauthenticate?operation=password'
        self.assertEqual(self.client.post(path).status_code,200)
        with self.client.session_transaction() as s:self.assertIn('oidc_proof',s)
        csrf=self.csrf(path);self.client.post(path,data={'csrf_token':csrf})
        with self.client.session_transaction() as s:self.assertNotIn('oidc_proof',s)

    def test_rotated_refresh_survives_following_introspection_outage(self):
        self.login();self.idp.rotate=True;self.idp.outage.add('/introspect')
        with self.client.session_transaction() as s:s['oidc_token']={**s['oidc_token'],'expires_at':0}
        self.assertEqual(self.client.get('/admin/').status_code,503)
        with self.client.session_transaction() as s:self.assertEqual(s['oidc_token']['refresh_token'],'refresh-2')
        self.idp.outage.clear();self.assertEqual(self.client.get('/admin/').status_code,302)

    def test_documentation_parses(self):
        from docutils.core import publish_doctree
        warnings=io.StringIO()
        publish_doctree(Path('/tests/oidc.rst').read_text(),settings_overrides={'halt_level':2,'warning_stream':warnings})
        self.assertEqual(warnings.getvalue(),'')


    def test_management_api_keeps_token_boundary(self):
        self.login()
        management=create_app_from_config(TestConfig(self.config.uri,API_TOKEN='unit-management-token'))
        management.session_store=self.app.session_store
        client=management.test_client();cookie=self.client.get_cookie(self.app.config['SESSION_COOKIE_NAME'])
        client.set_cookie(cookie.key,cookie.value)
        self.assertEqual(client.get('/api/v1/user').status_code,401)
        self.assertEqual(client.get('/api/v1/user',headers={'Authorization':'Bearer wrong-token'}).status_code,403)
        self.assertEqual(client.get('/api/v1/user',headers={'Authorization':'Bearer unit-management-token'}).status_code,200)

    def test_local_verification_rate_limit_and_atomic_proof_consumption(self):
        from concurrent.futures import ThreadPoolExecutor
        self.login();csrf=self.csrf('/admin/token/create')
        with patch.object(utils.limiter,'should_rate_limit_user',return_value=True):
            self.client.post('/admin/token/create',data={'csrf_token':csrf,'current_pw':'local-password','raw_password':'a'*32})
        self.assertEqual(len(self.user().tokens),0)
        self.reauthenticate()
        with self.client.session_transaction() as s:key=s['oidc_proof']
        def take():
            try:return self.app.session_store.take(key)
            except KeyError:return None
        with ThreadPoolExecutor(max_workers=2) as executor:values=list(executor.map(lambda _:take(),range(2)))
        self.assertEqual(sum(value is not None for value in values),1)

    def test_concurrent_provision_cannot_exceed_sqlite_domain_limit(self):
        from concurrent.futures import ThreadPoolExecutor
        domain=self.user().domain;domain.max_users=2;models.db.session.commit()
        self.app.config['OIDC_AUTH_CREATE']=True
        def create(email):
            with self.app.app_context():
                try:
                    oidc.provision(email,'New User')
                    return True
                except oidc.OidcError:
                    models.db.session.rollback()
                    return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(create,['new1@example.org','new2@example.org']))
        self.assertEqual(sum(results),1)
        self.assertEqual(models.User.query.count(),2)


    def test_header_proxy_creation_clears_previous_oidc_origin(self):
        import ipaddress
        self.login();self.app.config['PROXY_AUTH_CREATE']=True
        self.app.config['PROXY_AUTH_WHITELIST']={ipaddress.ip_network('127.0.0.0/8')}
        response=self.client.get('/sso/login',headers={'X-Auth-Email':'proxy@example.org'})
        self.assertEqual(response.location,'/admin')
        with self.client.session_transaction() as session:
            self.assertEqual(session['_user_id'],'proxy@example.org')
            self.assertNotIn('oidc_token',session)
            self.assertNotIn('auth_origin',session)
        self.idp.outage.add('/introspect')
        self.assertEqual(self.client.get('/admin/').status_code,302)

    def test_cache_ttl_validation(self):
        for value in ('-1','bad','1.5','true'):
            with self.subTest(value=value), patch.dict(os.environ,OIDC_INTROSPECTION_CACHE_TTL=value):
                with self.assertRaises(ValueError): configuration.ConfigManager().init_app(flask.Flask(__name__))
        for value in ('0','30'):
            with patch.dict(os.environ,OIDC_INTROSPECTION_CACHE_TTL=value):
                application=flask.Flask(__name__);configuration.ConfigManager().init_app(application)
                self.assertEqual(application.config['OIDC_INTROSPECTION_CACHE_TTL'],int(value))


if __name__ == '__main__':
    unittest.main()
