"""Verify the proxy and Webmail configuration at the same mount."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from jinja2 import Environment, FileSystemLoader
from socrate import web


TEMPLATES = Environment(loader=FileSystemLoader(Path('/tests/templates')))


class WebPathTest(unittest.TestCase):
    def config(self, base, **overrides):
        config = dict(WEB_ADMIN='/admin', WEB_WEBMAIL='/webmail', WEBROOT_REDIRECT='/webmail',
                      ADMIN=True, API=True, WEBMAIL='roundcube', WEBDAV='radicale',
                      HOSTNAMES='mail.example.org', MESSAGE_SIZE_LIMIT=50000000, RESOLVER='127.0.0.11')
        config.update(overrides)
        with patch.dict(os.environ, WEB_BASE_PATH=base):
            web.mount_paths(config, web.base_path())
        return config

    def test_invalid_base_paths(self):
        for value in ('/', '/mailu/', 'mailu', '/a//b', '/a/..', '/x;return', '/internal/ui',
                      '/webdav', '/mobileconfigs', '/Autodiscover/AutodiscoverXjson'):
            with self.subTest(value=value), patch.dict(os.environ, WEB_BASE_PATH=value):
                with self.assertRaisesRegex(ValueError, 'WEB_BASE_PATH'):
                    web.base_path()

    def test_front_default_and_subpath_configurations(self):
        for base in ('', '/services/mailu'):
            with self.subTest(base=base):
                config = self.config(base)
                front = TEMPLATES.get_template('front.conf').render(config)
                self.assertIn(f'location ~ ^{base}/(sso|static)/', front)
                self.assertIn(f'return 302 {base}/sso/login?url=$request_uri;', front)
                self.assertIn(f'location {base}/admin', front)
                self.assertIn(f'location {base}/webmail/sso.php', front)
                self.assertIn(f'try_files $uri {base}/webmail?homepage;', front)
                self.assertIn('auth_request /internal/auth/user;', front)
                self.assertIn('location /webdav {', front)
                self.assertIn('rewrite ^ /internal/autoconfig/mozilla break;', front)
        self.assertIn('location = /services/mailu {', front)
        self.assertIn('return 308 /services/mailu/$is_args$args;', front)
        self.assertIn('location ~ ^/services/mailu/api(?:/|$) {', front)

    def test_empty_redirect_and_root_webmail(self):
        front = TEMPLATES.get_template('front.conf')
        base = '/mailu'
        self.assertIn('try_files $uri =404;', front.render(self.config(base, WEBROOT_REDIRECT='')))
        overridden = front.render(self.config(base, WEBROOT_REDIRECT='none'))
        self.assertNotIn('location /mailu/ {', overridden)
        webmail = front.render(self.config(base, WEB_WEBMAIL='/'))
        self.assertEqual(webmail.count('location /mailu/ {'), 1)
        self.assertIn('rewrite ^/mailu/(.*) /$1 break;', webmail)
        self.assertIn('location /mailu/sso.php {', webmail)
        disabled = front.render(self.config(base, WEB_WEBMAIL='/', WEBMAIL='none', WEBROOT_REDIRECT='/admin/'))
        self.assertIn('try_files $uri /mailu/admin/?homepage;', disabled)

    def test_webmail_sso_paths_agree_in_both_clients(self):
        prefix = '/services/mailu'
        config = self.config(prefix, WEB_WEBMAIL='/team/inbox')
        roundcube = TEMPLATES.get_template('roundcube.php').render(config)
        self.assertIn(f"$config['request_path'] = '{prefix}/team/inbox';", roundcube)
        self.assertIn(f"'{prefix}/admin'", roundcube)
        self.assertIn(f"'{prefix}/sso/logout'", roundcube)
        config['WEBMAIL'] = 'snappymail'
        snappy = TEMPLATES.get_template('snappymail.ini').render(config)
        self.assertIn(f'custom_login_link = "{prefix}/team/inbox/sso.php"', snappy)
        self.assertIn(f'custom_logout_link = "{prefix}/sso/logout"', snappy)
        for app in ('roundcube', 'snappymail'):
            config['WEBMAIL'] = app
            fastcgi = TEMPLATES.get_template('webmail.conf').render(config)
            self.assertIn(f'SCRIPT_NAME {prefix}/team/inbox$fastcgi_script_name;', fastcgi)
