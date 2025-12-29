Fork Purpose and OIDC Support (English)
======================================

This fork adds OpenID Connect (OIDC) authentication support so Mailu can use an external identity provider for login.
Configuration is done via environment variables (see `docs/oidc.rst`), and enabling OIDC switches the login flow to the provider.

OIDC environment variables:

| Variable | Description |
| --- | --- |
| `OIDC_ENABLED` | Set to `true` to enable OIDC (default: disabled). |
| `OIDC_CLIENT_ID` | Client ID issued by your OIDC provider. |
| `OIDC_CLIENT_SECRET` | Client secret issued by your OIDC provider. |
| `OIDC_PROVIDER_INFO_URL` | Provider discovery URL (for example `https://accounts.google.com/.well-known/openid-configuration`). |
| `OIDC_BUTTON_NAME` | Label shown on the login button. |

Example:

```
OIDC_ENABLED=true
OIDC_CLIENT_ID=mailu
OIDC_CLIENT_SECRET=secret
OIDC_PROVIDER_INFO_URL=https://keycloak.example.com/auth/realms/mailu/.well-known/openid-configuration
OIDC_BUTTON_NAME=Keycloak
```

フォークの目的とOIDC対応 (日本語)
==============================

このフォークは、外部のOpenID Connect (OIDC) プロバイダーを使った認証に対応するためのものです。
OIDCの設定は環境変数で行い、`OIDC_ENABLED=true` を指定するとログインがOIDCプロバイダー経由になります。

OIDC関連の環境変数:

| 変数 | 説明 |
| --- | --- |
| `OIDC_ENABLED` | `true` で有効化 (デフォルトは無効)。 |
| `OIDC_CLIENT_ID` | OIDCプロバイダーで発行したクライアントID。 |
| `OIDC_CLIENT_SECRET` | OIDCプロバイダーで発行したクライアントシークレット。 |
| `OIDC_PROVIDER_INFO_URL` | プロバイダーのディスカバリーURL。 |
| `OIDC_BUTTON_NAME` | ログイン画面のボタン表示名。 |

例:

```
OIDC_ENABLED=true
OIDC_CLIENT_ID=mailu
OIDC_CLIENT_SECRET=secret
OIDC_PROVIDER_INFO_URL=https://keycloak.example.com/auth/realms/mailu/.well-known/openid-configuration
OIDC_BUTTON_NAME=Keycloak
```

<p align="leftr"><img src="docs/assets/logomark.png" alt="Mailu" height="200px"></p>

Mailu is a simple yet full-featured mail server as a set of Docker images.
It is free software (both as in free beer and as in free speech), open to
suggestions and external contributions. The project aims at providing people
with an easily setup, easily maintained and full-featured mail server while
not shipping proprietary software nor unrelated features often found in
popular groupware.

Most of the documentation is available on our [Website](https://mailu.io),
you can also [try our demo server](https://mailu.io/master/demo.html)
before setting up your own, and come [talk to us on Matrix](https://matrix.to/#/#mailu:tedomum.net).

Features
========

Main features include:

- **Standard email server**, IMAP and IMAP+, SMTP and Submission with auto-configuration profiles for clients
- **Advanced email features**, aliases, domain aliases, custom routing, full-text search of email attachments
- **Web access**, multiple Webmails and administration interface
- **User features**, aliases, auto-reply, auto-forward, fetched accounts, managesieve
- **Admin features**, global admins, announcements, per-domain delegation, quotas
- **Security**, enforced TLS, DANE, MTA-STS, Letsencrypt!, outgoing DKIM, anti-virus scanner, [Snuffleupagus](https://github.com/jvoisin/snuffleupagus/), block malicious attachments
- **Antispam**, auto-learn, greylisting, DMARC and SPF, anti-spoofing
- **Freedom**, all FOSS components, no tracker included

![Domains](docs/assets/screenshots/domains.png)

Contributing
============

Mailu is free software, open to suggestions and contributions. All
components are free software and compatible with the MIT license. All
specific configuration files, Dockerfiles and code are placed under the
MIT license.
