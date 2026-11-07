"""OIDC protocol and browser authentication boundaries.

Only discovery is cached on the application. Each exchange gets its own PyOIDC
client; transactions and one-use credential proofs live in the session backend.
"""
import copy
import pickle
import secrets
import threading
import time
from contextlib import contextmanager
from urllib.parse import parse_qs

import flask
import flask_login
import requests
from flask import current_app as app
from oic.oic import Client
from oic.oic.message import AuthorizationResponse, RegistrationResponse
from oic.oauth2.message import AccessTokenResponse, ROPCAccessTokenRequest
from oic.oauth2.grant import Token
from oic.extension.client import Client as ExtensionClient
from oic.utils.authn.client import CLIENT_AUTHN_METHOD
from oic.utils.settings import OicClientSettings, ClientSettings

TRANSACTION_TTL = 300
PROOF_TTL = 120
PREFIX = b'oidc-'


class OidcError(Exception):
    """Untrusted, rejected or invalid authentication; never log protocol payloads."""


class Unavailable(OidcError):
    """Temporary provider failure: preserve an existing browser session."""


class ConfigurationError(OidcError):
    """The configured provider cannot meet this application's contract."""


def _http_request(self, url, method='GET', **kwargs):
    try:
        response = super(type(self), self).http_request(url, method, **kwargs)
    except requests.RequestException:
        raise Unavailable('Identity provider is temporarily unavailable') from None
    if response.status_code >= 500 or response.status_code == 429:
        raise Unavailable('Identity provider is temporarily unavailable')
    return response


class ProtocolClient(Client):
    http_request = _http_request


class PasswordClient(ExtensionClient):
    http_request = _http_request


def normalize_email(value):
    from mailu import models
    if not isinstance(value, str) or value.count('@') != 1:
        raise OidcError('Identity provider did not return a valid email address')
    local, domain = value.split('@')
    # The same lowercasing and IDNA rules used by Mailu's email primary key.
    if not local or not domain or any(c.isspace() for c in value):
        raise OidcError('Identity provider did not return a valid email address')
    from mailu.ui.forms import LOCALPART_REGEX
    import re
    if not re.fullmatch(LOCALPART_REGEX, local):
        raise OidcError('Identity provider did not return a valid email address')
    try:
        return models.IdnaEmail().process_result_value(models.IdnaEmail().process_bind_param(value, None), None)
    except (ValueError, UnicodeError):
        raise OidcError('Identity provider did not return a valid email address') from None


def clear_browser_state():
    for name in ('oidc_transaction', 'oidc_proof'):
        if key := flask.session.pop(name, None):
            app.session_store.delete(key)
    for name in ('oidc_token', 'oidc_binding', 'auth_origin'):
        flask.session.pop(name, None)


def _put(kind, value, ttl):
    name = 'oidc_' + kind
    if previous := flask.session.pop(name, None):
        app.session_store.delete(previous)
    key = PREFIX + secrets.token_hex(32).encode()
    value = {**value, 'until': time.time() + ttl,
             'binding': flask.session.setdefault('oidc_binding', secrets.token_urlsafe(32))}
    app.session_store.put(key, pickle.dumps(value), ttl)
    flask.session[name] = key
    return value


def _load(kind, consume=False):
    key = flask.session.get('oidc_' + kind)
    if not isinstance(key, bytes) or not key.startswith(PREFIX):
        raise OidcError('Authentication verification is missing or already used')
    try:
        raw = app.session_store.take(key) if consume else app.session_store.get(key)
        value = pickle.loads(raw)
    except (KeyError, ValueError, pickle.UnpicklingError):
        raise OidcError('Authentication verification has expired or was already used') from None
    if consume:
        flask.session.pop('oidc_' + kind, None)
    if value['until'] <= time.time() or not secrets.compare_digest(value['binding'], flask.session.get('oidc_binding', '')):
        raise OidcError('Authentication verification has expired')
    return value


class OidcClient:
    def init_app(self, application):
        application.extensions['mailu_oidc'] = {'lock': threading.Lock(), 'provider': None,
                                               'retry_at': 0, 'expires': 0, 'error': None}
        application.before_request(enforce_browser_session)

    def is_enabled(self):
        return app.config['OIDC_ENABLED']

    def _new_client(self, password=False):
        cls, settings = (PasswordClient, ClientSettings) if password else (ProtocolClient, OicClientSettings)
        client = cls(client_authn_method=CLIENT_AUTHN_METHOD, settings=settings(timeout=5))
        client.store_registration_info(RegistrationResponse(client_id=app.config['OIDC_CLIENT_ID'],
            client_secret=app.config['OIDC_CLIENT_SECRET'], redirect_uris=[self.redirect_uri()]))
        return client

    def client(self, password=False):
        if not self.is_enabled():
            raise ConfigurationError('OIDC is disabled')
        runtime = app.extensions['mailu_oidc']
        with runtime['lock']:
            now = time.time()
            if now < runtime['retry_at']:
                raise runtime['error']('Identity provider unavailable; retry shortly')
            if not runtime['provider'] or runtime['expires'] <= now:
                try:
                    discovery = self._new_client()
                    provider = discovery.provider_config(app.config['OIDC_PROVIDER_INFO_URL'])
                    if not provider.get('introspection_endpoint'):
                        raise ConfigurationError('OIDC provider requires an introspection_endpoint')
                    runtime.update(provider=provider.to_dict(), keyjar=copy.deepcopy(discovery.keyjar),
                                   expires=now + 300, retry_at=0, error=None)
                except Exception as exc:
                    error = ConfigurationError if isinstance(exc, ConfigurationError) else Unavailable
                    runtime.update(retry_at=now + 10, error=error)
                    app.logger.warning('OIDC discovery failed: %s', 'introspection_endpoint is required' if error is ConfigurationError else 'provider unavailable')
                    raise error('OIDC provider requires introspection support' if error is ConfigurationError else 'Identity provider temporarily unavailable') from None
            client = self._new_client(password)
            client.handle_provider_config(copy.deepcopy(runtime['provider']), runtime['provider']['issuer'], keys=False)
            client.keyjar = copy.deepcopy(runtime['keyjar'])
            return client

    @staticmethod
    def redirect_uri():
        return 'https://' + app.config['OIDC_REDIRECT_HOST'] + flask.url_for('sso.login_oidc')

    def get_redirect_url(self):
        # Rendering the local login screen must never wait for discovery.
        return flask.url_for('sso.oidc_start', url=flask.request.args.get('url', '')) if self.is_enabled() else None

    def begin(self, destination, operation=None, target=None):
        client = self.client()
        if proof := flask.session.pop('oidc_proof', None):
            app.session_store.delete(proof)
        actor = flask.session.get('_user_id')
        tx = _put('transaction', {'state': secrets.token_urlsafe(32), 'nonce': secrets.token_urlsafe(32),
            'redirect_uri': self.redirect_uri(), 'destination': destination, 'operation': operation,
            'actor': actor, 'target': target, 'started': time.time()}, TRANSACTION_TTL)
        args = {'client_id': client.client_id, 'response_type': ['code'], 'scope': ['openid', 'email', 'profile'],
                'nonce': tx['nonce'], 'redirect_uri': tx['redirect_uri'], 'state': tx['state']}
        if operation:
            args.update(prompt='login', max_age=0)
        return client.construct_AuthorizationRequest(request_args=args).request(client.authorization_endpoint)

    def exchange_code(self, query):
        values = parse_qs(query, keep_blank_values=True)
        tx = _load('transaction')
        if len(values.get('state', [])) != 1 or not secrets.compare_digest(values['state'][0], tx['state']):
            raise OidcError('OIDC state does not match the initiating session')
        tx = _load('transaction', consume=True)  # atomic across workers, before library processing
        if 'error' in values or len(values.get('code', [])) != 1 or not values['code'][0]:
            raise OidcError('OIDC login was cancelled or the response is invalid')
        if tx['operation'] and flask.session.get('_user_id') != tx['actor']:
            raise OidcError('The acting user changed during reauthentication')
        client = self.client()
        try:
            client.state2nonce[tx['state']] = tx['nonce']
            client.parse_response(AuthorizationResponse, info=query, sformat='urlencoded')
            response = client.do_access_token_request(state=tx['state'], request_args={
                'code': values['code'][0], 'redirect_uri': tx['redirect_uri']}, authn_method='client_secret_basic')
            self._require_token(response)
            identity = response.get('id_token')
            if not identity or not identity.get('sub') or not identity.get('nonce'):
                raise OidcError('OIDC response is missing identity claims')
            # PyOIDC verifies signature while parsing; also explicitly enforce protocol claims.
            if identity.jws_header.get('alg') == 'none':
                raise OidcError('Unsigned ID Token is not accepted')
            client.verify_id_token(identity, {'nonce': tx['nonce'], 'response_type': ['code']})
            info = client.do_user_info_request(access_token=response['access_token'], state=tx['state'])
            if not info.get('sub') or info['sub'] != identity['sub']:
                raise OidcError('OIDC UserInfo subject does not match')
            email = normalize_email(info.get('email'))
            if tx['operation']:
                auth_time = identity.get('auth_time')
                if email != tx['actor'] or not isinstance(auth_time, (int, float)) or isinstance(auth_time, bool) or not tx['started'] - 5 <= auth_time <= time.time() + 5:
                    raise OidcError('Fresh authentication for the acting account is required')
            try:
                live = pickle.loads(app.session_store.get(flask.session._key))
            except (KeyError, TypeError):
                raise OidcError('Initiating session is no longer valid') from None
            if live.get('oidc_binding') != tx['binding'] or live.get('_user_id') != tx['actor']:
                raise OidcError('Initiating session changed during authentication')
            return {'email': email, 'name': (info.get('name') if isinstance(info.get('name'), str) else email)[:160]}, {**self._token(response, email), 'sub': identity['sub']}, tx
        except Unavailable:
            raise
        except Exception:
            raise OidcError('Identity provider response could not be verified') from None

    @staticmethod
    def _require_token(response):
        if not isinstance(response, AccessTokenResponse) or not isinstance(response.get('access_token'), str) or not response['access_token']:
            raise OidcError('Missing access token')
        if str(response.get('token_type', '')).lower() != 'bearer':
            raise OidcError('Unsupported access-token type')
        if 'refresh_token' in response and (not isinstance(response['refresh_token'], str) or not response['refresh_token']):
            raise OidcError('Invalid refresh token')
        expiry = response.get('expires_in')
        if isinstance(expiry, bool) or not isinstance(expiry, int) or expiry <= 0:
            raise OidcError('Missing or invalid access-token lifetime')

    def _token(self, response, email, previous=None):
        self._require_token(response)
        return {'access_token': response['access_token'], 'expires_at': time.time() + response['expires_in'],
                'refresh_token': response.get('refresh_token', (previous or {}).get('refresh_token')),
                'email': email, 'sub': (previous or {}).get('sub'), 'checked_until': 0}

    def get_token(self, username, password):
        client = self.client(password=True)
        try:
            args = {'username': username, 'password': password, 'grant_type': 'password',
                    'client_id': client.client_id, 'client_secret': app.config['OIDC_CLIENT_SECRET']}
            url, body, http_args, _ = client.request_info(ROPCAccessTokenRequest, request_args=args, method='POST')
            response = client.request_and_return(url, AccessTokenResponse, 'POST', body, 'json', '', http_args)
            self._require_token(response)
            # Password grants still must identify the requested Mailu account.
            info = self.client().do_user_info_request(access_token=response['access_token'])
            if not info.get('sub') or normalize_email(info.get('email')) != username:
                return None
            return {**self._token(response, username), 'sub': info['sub']}
        except Unavailable:
            raise
        except Exception:
            return None

    def check_validity(self, token):
        if not self.is_enabled():
            raise ConfigurationError('OIDC is disabled')
        if not isinstance(token, dict) or token.get('email') != flask.session.get('_user_id'):
            raise OidcError('OIDC session must be authenticated again')
        now = time.time()
        if token.get('checked_until', 0) > now and token['expires_at'] > now:
            return token
        if token['expires_at'] <= now:
            if not token.get('refresh_token'):
                raise OidcError('OIDC session expired')
            client = self.client()
            try:
                response = client.do_access_token_refresh(request_args={'refresh_token': token['refresh_token']},
                    authn_method='client_secret_basic', token=Token({'access_token': token['access_token'],
                        'refresh_token': token['refresh_token'], 'token_type': 'Bearer'}))
                identity = response.get('id_token')
                if identity:
                    if identity.jws_header.get('alg') == 'none' or identity.get('sub') != token.get('sub'):
                        raise OidcError('Refresh identity does not match')
                    client.verify_id_token(identity, {'response_type': ['code']})
                token = self._token(response, token['email'], token)
                # Retain rotated credentials even if the following introspection is down.
                flask.session['oidc_token'] = token
            except Unavailable:
                raise
            except Exception:
                raise OidcError('OIDC refresh was refused') from None
        client = self.client(password=True)
        try:
            response = client.do_token_introspection(request_args={'token': token['access_token'],
                'token_type_hint': 'access_token'}, authn_method='client_secret_basic')
            if response.get('active') is not True:
                raise OidcError('OIDC token is inactive')
            if response.get('sub', token.get('sub')) != token.get('sub'):
                raise OidcError('Introspection identity does not match')
            until = min(token['expires_at'], time.time() + app.config['OIDC_INTROSPECTION_CACHE_TTL'])
            if 'exp' in response:
                exp = response['exp']
                if isinstance(exp, bool) or not isinstance(exp, (int, float)) or exp <= time.time():
                    raise OidcError('OIDC token is expired')
                until = min(until, exp)
            token = {**token, 'checked_until': until}
            return token
        except Unavailable:
            raise
        except OidcError:
            raise
        except Exception:
            raise OidcError('OIDC introspection response is invalid') from None


oidc_client = OidcClient()


def enforce_browser_session():
    from mailu import models
    endpoint = flask.request.endpoint or ''
    if endpoint in {'internal.nginx_authentication', 'internal.basic_authentication'} or endpoint.startswith('api'):
        return
    uid = flask.session.get('_user_id')
    if not uid:
        return
    user = models.User.get(uid)
    if not user or not user.enabled:
        clear_browser_state()
        flask_login.logout_user()
        flask.session.destroy()
        if endpoint in {'sso.login', 'sso.logout'}:
            return
        flask.abort(403)
    # Credential endpoints verify their own input, never a browser's OIDC token.
    endpoint = flask.request.endpoint or ''
    if endpoint in {'sso.login', 'sso.logout', 'sso.oidc_start', 'sso.login_oidc', 'sso.oidc_reauthenticate',
                    'internal.nginx_authentication', 'internal.basic_authentication', 'ping', 'static'} or endpoint.startswith('api'):
        return
    if flask.session.get('auth_origin') == 'oidc' or 'oidc_token' in flask.session:
        try:
            flask.session['oidc_token'] = oidc_client.check_validity(flask.session.get('oidc_token'))
        except Unavailable:
            flask.abort(403 if endpoint in {'internal.user_authentication', 'internal.admin_authentication'} else 503,
                        'Identity provider temporarily unavailable. Retry or sign in with your local password.')
        except OidcError:
            clear_browser_state()
            flask_login.logout_user()
            flask.session.destroy()
            flask.abort(403)


def provision(email, name):
    from mailu import models
    from sqlalchemy.exc import IntegrityError
    user = models.User.get(email)
    if user:
        if not user.enabled:
            raise OidcError('Mailu account is disabled')
        return user
    if not app.config['OIDC_AUTH_CREATE']:
        raise OidcError('Mailu account does not exist')
    local, domain_name = email.split('@')
    # Serialize capacity checks against the same domain in production databases.
    domain = models.Domain.query.filter_by(name=domain_name).with_for_update().first()
    if domain:
        # A write lock also serializes capacity checks on SQLite (FOR UPDATE is ignored there).
        models.Domain.query.filter_by(name=domain_name).update({
            models.Domain.max_users: models.Domain.max_users,
            models.Domain.updated_at: models.Domain.updated_at}, synchronize_session=False)
    if not domain or domain.has_email(local) or models.Alias.resolve(local, domain_name):
        raise OidcError('Mailu domain is unknown or email address is already used')
    if domain.max_users != -1 and models.User.query.filter_by(domain_name=domain_name).count() >= domain.max_users:
        raise OidcError('Mailu domain user limit reached')
    quota = int(app.config['DEFAULT_QUOTA'])
    if domain.max_quota_bytes:
        quota = min(quota, domain.max_quota_bytes)
    user = models.User(domain=domain, localpart=local, password='openid',
                       displayed_name=name, global_admin=False, quota_bytes=quota)
    models.db.session.add(user)
    try:
        models.db.session.commit()
    except IntegrityError:
        models.db.session.rollback()
        user = models.User.get(email)
        if not user or not user.enabled:
            raise OidcError('Mailu account could not be created') from None
    return user


def proof_matches(operation, target):
    try:
        proof = _load('proof')
        return proof['actor'] == flask.session.get('_user_id') and proof['operation'] == operation and proof['target'] == target
    except OidcError:
        return False


@contextmanager
def verify_operation(operation, target, password):
    """Verify the actor, atomically reserve proof, restore only on failed writes."""
    from mailu import utils
    actor = flask_login.current_user
    proof = None
    key = None
    if proof_matches(operation, target):
        key = flask.session['oidc_proof']
        proof = _load('proof', consume=True)
    else:
        ip = flask.request.headers.get('X-Real-IP', flask.request.remote_addr)
        cookie, cookie_user = utils.limiter.parse_device_cookie(flask.request.cookies.get('rate_limit'))
        if utils.limiter.should_rate_limit_user(actor.email, ip, cookie, cookie_user) or utils.limiter.should_rate_limit_ip(ip):
            raise OidcError('Too many verification attempts (rate-limit)')
        if not password or not actor.has_local_password or not actor.check_password_internal(password):
            utils.limiter.rate_limit_user(actor.email, ip, cookie, cookie_user, password or '')
            raise OidcError('Current local password or fresh OIDC authentication is required')
    try:
        yield
    except Exception:
        if proof and proof['until'] > time.time():
            app.session_store.put(key, pickle.dumps(proof), max(1, int(proof['until'] - time.time())))
            flask.session['oidc_proof'] = key
        raise
