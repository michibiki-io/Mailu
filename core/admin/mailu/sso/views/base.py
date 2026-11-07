from werkzeug.utils import redirect
from mailu import models, utils
from mailu.sso import sso, forms
from mailu.ui import access

from flask import current_app as app
from flask_babel import lazy_gettext as _
import flask
import flask_login
import secrets
import ipaddress
from urllib.parse import urlparse, urljoin, unquote

from mailu import oidc
import flask_wtf


@sso.route('/login', methods=['GET', 'POST'])
def login():
    if flask.request.headers.get(app.config['PROXY_AUTH_HEADER']) and not 'noproxyauth' in flask.request.url:
        return _proxy()

    client_ip = flask.request.headers.get('X-Real-IP', flask.request.remote_addr)
    client_port = flask.request.headers.get('X-Real-Port', None)
    form = forms.LoginForm()

    fields = []

    if 'url' in flask.request.args and not 'homepage' in flask.request.url:
        fields.append(form.submitAdmin)
    else:
        form.submitAdmin.label.text = form.submitAdmin.label.text + ' Admin'
        form.submitWebmail.label.text = form.submitWebmail.label.text + ' Webmail'
        if str(app.config["WEBMAIL"]).upper() != "NONE":
            fields.append(form.submitWebmail)
        if str(app.config["ADMIN"]).upper() != "FALSE":
            fields.append(form.submitAdmin)
    fields = [fields]

    if form.validate_on_submit():
        if destination := _has_usable_redirect():
            pass
        else:
            if form.submitAdmin.data:
                destination = app.config['WEB_ADMIN']
            elif form.submitWebmail.data:
                destination = app.config['WEB_WEBMAIL']
        device_cookie, device_cookie_username = utils.limiter.parse_device_cookie(flask.request.cookies.get('rate_limit'))
        username = form.email.data
        if not utils.is_app_token(form.pw.data):
            if username != device_cookie_username and utils.limiter.should_rate_limit_ip(client_ip):
                flask.flash(_('Too many attempts from your IP (rate-limit)'), 'error')
                return flask.render_template('login.html', form=form, fields=fields)
            if utils.limiter.should_rate_limit_user(username, client_ip, device_cookie, device_cookie_username):
                flask.flash(_('Too many attempts for this user (rate-limit)'), 'error')
                return flask.render_template('login.html', form=form, fields=fields)
        user = models.User.login(username, form.pw.data)
        if user:
            origin, _, token = flask.g.mailu_credential
            oidc.clear_browser_state()
            flask.session['auth_origin'] = origin
            if token:
                flask.session['oidc_token'] = token
            flask.session.regenerate()
            flask_login.login_user(user)
            if user.change_pw_next_login:
                flask.session['redirect_to'] = destination
                destination = flask.url_for('sso.pw_change')
            response = flask.redirect(destination)
            response.set_cookie('rate_limit', utils.limiter.device_cookie(username), max_age=31536000, path=flask.url_for('sso.login'), secure=app.config['SESSION_COOKIE_SECURE'], httponly=True)
            flask.current_app.logger.info(f'Login attempt for: {username}/sso/{flask.request.headers.get("X-Forwarded-Proto")} from: {client_ip}/{client_port}: success: password: {form.pwned.data}')
            if msg := utils.isBadOrPwned(form):
                flask.flash(msg, "error")
            return response
        else:
            utils.limiter.rate_limit_user(username, client_ip, device_cookie, device_cookie_username, form.pw.data) if models.User.get(username) else utils.limiter.rate_limit_ip(client_ip, username)
            flask.current_app.logger.info(f'Login attempt for: {username}/sso/{flask.request.headers.get("X-Forwarded-Proto")} from: {client_ip}/{client_port}: failed: badauth: {utils.truncated_pw_hash(form.pw.data)}')
            flask.flash(_('Wrong e-mail or password'), 'error')
    return flask.render_template('login.html', form=form, fields=fields, oidc_enabled=app.config['OIDC_ENABLED'], oidc_redirect_url=utils.oidc_client.get_redirect_url())

@sso.route('/oidc/start')
def oidc_start():
    try:
        return redirect(utils.oidc_client.begin(_has_usable_redirect() or app.config['WEB_ADMIN']))
    except oidc.OidcError as exc:
        models.db.session.rollback()
        app.logger.info('OIDC authentication refused: %s', exc)
        flask.flash(str(exc), 'error')
        return redirect(flask.url_for('sso.login'))


@sso.route('/oidc/reauthenticate', methods=['GET', 'POST'])
@access.authenticated
def oidc_reauthenticate():
    operation = flask.request.args.get('operation')
    target = flask.request.args.get('target', flask_login.current_user.email)
    if operation not in {'token', 'password', 'forced_password'}:
        flask.abort(400)
    user = models.User.get(target) or flask.abort(404)
    actor = flask_login.current_user
    if target != actor.email and (operation != 'token' or user.domain not in actor.get_managed_domains()):
        flask.abort(403)
    endpoints = {'token': 'ui.token_create', 'password': 'ui.user_password_change', 'forced_password': 'sso.pw_change'}
    destination = flask.url_for(endpoints[operation], **({'user_email': target} if operation == 'token' and target != actor.email else {}))
    form = flask_wtf.FlaskForm()
    if form.validate_on_submit():
        try:
            return redirect(utils.oidc_client.begin(destination, operation, target))
        except oidc.OidcError as exc:
            flask.flash(str(exc), 'error')
    return flask.render_template('oidc_reauthenticate.html', form=form, destination=destination)


@sso.route('/login/oidc', methods=['GET'])
def login_oidc():
    if not app.config['OIDC_ENABLED']:
        return redirect(flask.url_for('sso.login'))
    try:
        try:
            query = flask.request.query_string.decode('ascii')
        except UnicodeError:
            raise oidc.OidcError('Malformed OIDC callback') from None
        data, token, tx = utils.oidc_client.exchange_code(query)
        if tx['operation']:
            user = models.User.get(tx['actor'])
            if not user or not user.enabled or user.email != data['email']:
                raise oidc.OidcError('Fresh authentication must verify the current Mailu account')
            oidc._put('proof', {'actor': user.email, 'operation': tx['operation'], 'target': tx['target']}, oidc.PROOF_TTL)
            # A fresh browser exchange can also recover an OIDC-origin session.
            if flask.session.get('auth_origin') == 'oidc':
                flask.session['oidc_token'] = token
            return redirect(tx['destination'])
        ip = flask.request.headers.get('X-Real-IP', flask.request.remote_addr)
        cookie, cookie_user = utils.limiter.parse_device_cookie(flask.request.cookies.get('rate_limit'))
        if utils.limiter.should_rate_limit_ip(ip) or utils.limiter.should_rate_limit_user(data['email'], ip, cookie, cookie_user):
            raise oidc.OidcError('Too many attempts (rate-limit)')
        existing = flask.session.get('_user_id')
        if existing and existing != data['email']:
            raise oidc.OidcError('Sign out before signing in as another account')
        user = oidc.provision(data['email'], data['name'])
        oidc.clear_browser_state()
        flask.session['auth_origin'] = 'oidc'
        flask.session['oidc_token'] = token
        flask.session.regenerate()
        flask_login.login_user(user)
        destination = tx['destination']
        if user.change_pw_next_login:
            flask.session['redirect_to'] = destination
            destination = flask.url_for('sso.pw_change')
        return redirect(destination)
    except oidc.OidcError as exc:
        models.db.session.rollback()
        app.logger.info('OIDC authentication refused: %s', exc)
        flask.flash(str(exc), 'error')
        return redirect(flask.url_for('sso.login'))


@sso.route('/pw_change', methods=['GET', 'POST'])
@access.authenticated
def pw_change():
    client_ip = flask.request.headers.get('X-Real-IP', flask.request.remote_addr)
    client_port = flask.request.headers.get('X-Real-Port', None)
    form = forms.PWChangeForm()

    if form.validate_on_submit():
        if msg := utils.isBadOrPwned(form):
            flask.flash(msg, "error")
            return flask.redirect(flask.url_for('sso.pw_change'))
        if form.oldpw.data == form.pw2.data:
            # TODO: fuzzy match?
            flask.flash(_("The new password can't be the same as the old password"), "error")
            return flask.redirect(flask.url_for('sso.pw_change'))
        if form.pw.data != form.pw2.data:
            flask.flash(_("The new passwords don't match"), "error")
            return flask.redirect(flask.url_for('sso.pw_change'))
        user = flask_login.current_user._get_current_object()
        try:
            with oidc.verify_operation('forced_password', user.email, form.oldpw.data):
                user.set_password(form.pw.data, keep_sessions={flask.session.sid})
                user.change_pw_next_login = False
                models.db.session.commit()
        except oidc.OidcError as exc:
            flask.flash(str(exc), 'error')
        else:
            flask.session.regenerate()
            flask_login.login_user(user)

            flask.current_app.logger.info(f'Forced password change by {user} from: {client_ip}/{client_port}: success: password: {form.pwned.data}')
            destination = flask.session.pop('redirect_to', None) or app.config['WEB_ADMIN']
            return flask.redirect(destination)
        flask.flash(_("The current password is incorrect!"), "error")

    return flask.render_template('pw_change.html', form=form, reauth_url=flask.url_for('sso.oidc_reauthenticate', operation='forced_password'))

@sso.route('/logout', methods=['GET'])
@access.authenticated
def logout():
    return logout_internal()


def logout_internal():
    oidc.clear_browser_state()
    flask_login.logout_user()
    flask.session.destroy()
    response = flask.redirect(app.config['PROXY_AUTH_LOGOUT_URL'] or flask.url_for('.login'))
    for cookie in ['roundcube_sessauth', 'roundcube_sessid', 'smsession']:
        response.set_cookie(cookie, 'empty', expires=0)
    return response

"""
Redirect to the url passed in parameter if any; Ensure that this is not an open-redirect too...
https://cheatsheetseries.owasp.org/cheatsheets/Unvalidated_Redirects_and_Forwards_Cheat_Sheet.html
"""
def _has_usable_redirect(is_proxied=False):
    if 'homepage' in flask.request.url and not is_proxied:
        return None
    if url := flask.request.args.get('url'):
        target = urlparse(urljoin(flask.request.url, unquote(url)))
        if target.scheme in {'http', 'https'} and target.netloc == urlparse(flask.request.url).netloc:
            return target.geturl()
    return None

"""
https://mailu.io/master/configuration.html#header-authentication-using-an-external-proxy
"""
def _proxy():
    proxy_ip = flask.request.headers.get('X-Forwarded-By', flask.request.remote_addr)
    ip = ipaddress.ip_address(proxy_ip)
    client_ip = flask.request.headers.get('X-Real-IP', flask.request.remote_addr)
    if not any(ip in cidr for cidr in app.config['PROXY_AUTH_WHITELIST']):
        flask.current_app.logger.error(f'Login failed by proxy - not on whitelist: from {client_ip} through {flask.request.remote_addr}.')
        return flask.abort(500, '%s is not on PROXY_AUTH_WHITELIST' % proxy_ip)

    email = flask.request.headers.get(app.config['PROXY_AUTH_HEADER'])
    if not email:
        flask.current_app.logger.error(f'Login failed by proxy - no header: from {client_ip} through {flask.request.remote_addr}.')
        return flask.abort(500, 'No %s header' % app.config['PROXY_AUTH_HEADER'])

    url = _has_usable_redirect(True) or app.config['WEB_ADMIN']

    user = models.User.get(email)
    if user:
        if not user.enabled:
            flask.abort(403)
        oidc.clear_browser_state()
        flask.session.regenerate()
        flask_login.login_user(user)
        flask.current_app.logger.info(f'Login succeeded by proxy created user: {user} from {client_ip} through {flask.request.remote_addr}.')
        return flask.redirect(url)

    if not app.config['PROXY_AUTH_CREATE']:
        flask.current_app.logger.warning(f'Login failed by proxy - does not exist: {user} from {client_ip} through {flask.request.remote_addr}.')
        return flask.abort(500, 'You don\'t exist. Go away! (%s)' % email)

    client_ip = flask.request.headers.get('X-Real-IP', flask.request.remote_addr)
    try:
        localpart, desireddomain = email.rsplit('@')
    except Exception as e:
        flask.current_app.logger.error('Error creating a new user via proxy for %s from %s: %s' % (email, client_ip, str(e)), e)
        return flask.abort(500, 'You don\'t exist. Go away! (%s)' % email)
    domain = models.Domain.query.get(desireddomain) or flask.abort(500, 'You don\'t exist. Go away! (domain=%s)' % desireddomain)
    if not domain.max_users == -1 and len(domain.users) >= domain.max_users:
        flask.current_app.logger.warning('Too many users for domain %s' % domain)
        return flask.abort(500, 'Too many users in (domain=%s)' % domain)
    user = models.User(localpart=localpart, domain=domain)
    user.set_password(secrets.token_urlsafe(), keep_sessions=set(flask.session))
    models.db.session.add(user)
    models.db.session.commit()
    oidc.clear_browser_state()
    flask.session.regenerate()
    flask_login.login_user(user)
    user.send_welcome()
    flask.current_app.logger.info(f'Login succeeded by proxy created user: {user} from {client_ip} through {flask.request.remote_addr}.')
    return flask.redirect(url)
