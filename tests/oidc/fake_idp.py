"""Deterministic OIDC responses for the Flask and container integration tests."""
import json
import time
from urllib.parse import parse_qs, urlsplit

import requests
from Cryptodome.PublicKey import RSA
from jwkest.jwk import RSAKey
from oic.oic.message import IdToken

ISSUER = 'https://idp.example.org'
EMAIL = 'alice@example.org'


class FakeIdP:
    key = RSAKey(key=RSA.generate(2048), use='sig', kid='test-key')

    def __init__(self, issuer=ISSUER, email=EMAIL):
        self.issuer = issuer
        self.calls = []
        self.nonce = None
        self.claims = {}
        self.email = email
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
        self.refresh_id_token = False

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
            data = {'issuer': self.issuer, 'authorization_endpoint': self.issuer + '/authorize',
                    'token_endpoint': self.issuer + '/token', 'userinfo_endpoint': self.issuer + '/userinfo',
                    'jwks_uri': self.issuer + '/jwks', 'response_types_supported': ['code'],
                    'subject_types_supported': ['public'], 'id_token_signing_alg_values_supported': ['RS256']}
            if self.introspection:
                data['introspection_endpoint'] = self.issuer + '/introspect'
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
                if grant == 'authorization_code' or (grant == 'refresh_token' and self.refresh_id_token):
                    now = int(time.time())
                    claims = {'iss': self.issuer, 'aud': ['mailu'], 'sub': self.sub, 'iat': now,
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
