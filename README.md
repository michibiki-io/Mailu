# Mailu fork / Mailu フォーク

## Table of Contents / 目次

- [English](#english)
  - [Overview](#overview)
  - [Fork images](#fork-images)
  - [OpenID Connect](#openid-connect)
  - [Web UI paths](#web-ui-paths)
  - [Contributing](#contributing)
- [日本語](#日本語)
  - [概要](#概要)
  - [フォークのイメージ](#フォークのイメージ)
  - [OpenID Connect の設定](#openid-connect-の設定)
  - [Web UI の公開パス](#web-ui-の公開パス)
  - [コントリビューション](#コントリビューション)

## English

### Overview

<img src="docs/assets/logomark.png" alt="Mailu" height="200">

Mailu is a full-featured mail server distributed as Docker images. This fork adds OpenID Connect (OIDC) login and lets operators mount the Web UI under a shared URL path.

- Mailu supports SMTP, Submission, IMAP, and client autoconfiguration.
- Mailbox features include aliases, domain aliases, custom routing, full-text attachment search, auto-reply, forwarding, account fetching, and ManageSieve.
- Users can access mail through Roundcube or SnappyMail. The administration interface supports global and delegated administrators, announcements, and quotas.
- Security and antispam features include TLS, Let's Encrypt, DANE, MTA-STS, DKIM, SPF, DMARC, greylisting, spam learning, antivirus, attachment filtering, and [Snuffleupagus](https://github.com/jvoisin/snuffleupagus/).

![Mailu domain administration](docs/assets/screenshots/domains.png)

Visit the [Mailu website and documentation](https://mailu.io), try the [demo](https://mailu.io/master/demo.html), or join the [Matrix room](https://matrix.to/#/#mailu:tedomum.net).

### Fork images

Deploy the front, admin, and webmail images from the same [fork release](https://github.com/michibiki-io/Mailu/releases) with a single shared tag. Use the matching upstream Mailu version for the other Mailu images, including Postfix and the mailbox Dovecot.

| Service | Fork image |
| --- | --- |
| front | `ghcr.io/michibiki-io/mailu-nginx` |
| admin | `ghcr.io/michibiki-io/mailu-admin` |
| webmail | `ghcr.io/michibiki-io/mailu-webmail` |

### OpenID Connect

OIDC login and local passwords can coexist on the same Mailu account. With OIDC enabled, the login page offers an additional sign-in button. Configure the admin container with a confidential OIDC client and the provider's issuer URL. PyOIDC appends `/.well-known/openid-configuration`. Use the public hostname, with a port if needed, in `OIDC_REDIRECT_HOST`.

```dotenv
OIDC_ENABLED=true
OIDC_CLIENT_ID=mailu
OIDC_CLIENT_SECRET=<client secret>
OIDC_PROVIDER_INFO_URL=https://keycloak.example.com/realms/mailu
OIDC_BUTTON_NAME=Keycloak
OIDC_REDIRECT_HOST=mail.example.org
```

Register the exact HTTPS callback URI at the identity provider.

| Deployment | Callback URI |
| --- | --- |
| Root | `https://mail.example.org/sso/login/oidc` |
| `WEB_BASE_PATH=/mailu` | `https://mail.example.org/mailu/sso/login/oidc` |

The provider must support the authorization code flow, signed ID tokens, UserInfo, and token introspection. Discovery must advertise `introspection_endpoint`. See the [OIDC configuration and provider requirements](docs/oidc.rst).

### Web UI paths

Leave `WEB_BASE_PATH` unset or empty for a root deployment. To publish the Web UI under `/mailu`, set `WEB_BASE_PATH=/mailu` on front, admin, and the enabled webmail. With the default Web UI paths, admin is available at `/mailu/admin` and webmail at `/mailu/webmail/`. Autoconfiguration and WebDAV endpoints retain their root-level paths. See the [subpath deployment guide](docs/web-subpath.rst).

### Contributing

Mailu is free and open-source software and welcomes suggestions and contributions. Mailu's code, Dockerfiles, and configuration are distributed under the [MIT license](LICENSE.md). See the [contribution guide](CONTRIBUTING.md).

## 日本語

### 概要

<img src="docs/assets/logomark.png" alt="Mailu" height="200">

Mailu は、Docker イメージで提供するメールサーバーです。
このフォークでは OpenID Connect（OIDC）でログインでき、Web UI を共通のサブパスで公開できます。

- メールプロトコルと設定。SMTP、Submission、IMAP、メールクライアントの自動設定。
- メールボックス機能。エイリアス、ドメインエイリアス、カスタムルーティング、添付ファイルの全文検索、自動返信、転送、外部アカウントからのメール取得、ManageSieve。
- Web インターフェース。Roundcube または SnappyMail と、全体管理者、ドメインごとの権限委譲、告知、容量制限に対応する管理画面。
- セキュリティと迷惑メール対策。TLS、Let's Encrypt、DANE、MTA-STS、DKIM、SPF、DMARC、グレーリスティング、迷惑メールの学習、ウイルス検査、添付ファイルのフィルタリング、[Snuffleupagus](https://github.com/jvoisin/snuffleupagus/)。

![Mailu のドメイン管理画面](docs/assets/screenshots/domains.png)

[Mailu の公式サイトとドキュメント](https://mailu.io)、[デモ](https://mailu.io/master/demo.html)、[Matrix ルーム](https://matrix.to/#/#mailu:tedomum.net)を利用できます。

### フォークのイメージ

front、admin、webmail には、同じ[フォークのリリース](https://github.com/michibiki-io/Mailu/releases)から同一タグのイメージを指定します。
Postfix やメールボックス用 Dovecot など、ほかの Mailu イメージには対応する上流 Mailu のバージョンを指定します。

| サービス | フォークのイメージ |
| --- | --- |
| front | `ghcr.io/michibiki-io/mailu-nginx` |
| admin | `ghcr.io/michibiki-io/mailu-admin` |
| webmail | `ghcr.io/michibiki-io/mailu-webmail` |

### OpenID Connect の設定

同じ Mailu アカウントで、OIDC とローカルパスワードを併用できます。
OIDC を有効にすると、ログイン画面に OIDC 用のボタンが追加されます。
admin コンテナに、機密クライアントの情報と IdP の発行者（issuer）URL を設定します。
PyOIDC は発行者 URL に `/.well-known/openid-configuration` を追加します。
`OIDC_REDIRECT_HOST` には公開ホスト名を指定し、必要に応じてポート番号を付けます。

```dotenv
OIDC_ENABLED=true
OIDC_CLIENT_ID=mailu
OIDC_CLIENT_SECRET=<client secret>
OIDC_PROVIDER_INFO_URL=https://keycloak.example.com/realms/mailu
OIDC_BUTTON_NAME=Keycloak
OIDC_REDIRECT_HOST=mail.example.org
```

IdP に、構成に合った HTTPS コールバック URI を正確に登録します。

| 配備先 | コールバック URI |
| --- | --- |
| ルート | `https://mail.example.org/sso/login/oidc` |
| `WEB_BASE_PATH=/mailu` | `https://mail.example.org/mailu/sso/login/oidc` |

IdP には、認可コードフロー、署名付き ID トークン、UserInfo、トークンイントロスペクションが必要です。
ディスカバリー情報には `introspection_endpoint` が必要です。
詳細は [OIDC の設定と IdP の要件](docs/oidc.rst)を参照してください。

### Web UI の公開パス

ルートで公開する場合は、`WEB_BASE_PATH` を未設定または空にします。
`/mailu` 配下で公開する場合は、front、admin、有効な webmail に `WEB_BASE_PATH=/mailu` を設定します。
既定の設定では、管理画面は `/mailu/admin`、Web メールは `/mailu/webmail/` で利用できます。
メールクライアントの自動設定と WebDAV のエンドポイントは、引き続きルート直下の既存パスを使います。
詳細は[サブパスでの公開手順](docs/web-subpath.rst)を参照してください。

### コントリビューション

Mailu は自由に使えるオープンソースソフトウェアです。提案やコントリビューションを歓迎します。
Mailu のコード、Dockerfile、設定ファイルは [MIT ライセンス](LICENSE.md)で配布しています。
参加方法は[コントリビューションガイド](CONTRIBUTING.md)を参照してください。
