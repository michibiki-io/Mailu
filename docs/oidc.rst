External OpenID Connect Provider
================================

This page is the single OIDC configuration and behavior reference for this fork.
OIDC and local passwords coexist on the same Mailu account. The changes are
contained in the admin application; front, Dovecot and Postfix need no OIDC patch.

Configuration
-------------

* ``OIDC_ENABLED`` (default ``false``): enable OIDC.
* ``OIDC_PROVIDER_INFO_URL``: the provider's issuer URL (default
  ``https://localhost/info`` is a placeholder; set your real issuer), for example
  ``https://keycloak.example.com/realms/mailu``. PyOIDC appends
  ``/.well-known/openid-configuration``; do not append it yourself.
* ``OIDC_CLIENT_ID`` and ``OIDC_CLIENT_SECRET``: a confidential OIDC client.
* ``OIDC_BUTTON_NAME`` (default ``OpenID Connect``): login button label.
* ``OIDC_REDIRECT_HOST`` (default ``mail.mailu.io``): public Mailu hostname,
  optionally including a port, without scheme or path. Register the exact HTTPS
  callback ``https://<OIDC_REDIRECT_HOST>/sso/login/oidc`` at the provider.
* ``OIDC_AUTH_CREATE`` (boolean, default ``false``): allow normal browser OIDC
  login to create ordinary users in existing Mailu domains. This is independent
  of header authentication's ``PROXY_AUTH_CREATE``.
* ``OIDC_INTROSPECTION_CACHE_TTL`` (nonnegative integer seconds, default ``30``):
  cache positive introspection in server-side sessions, never beyond token expiry.
  ``0`` checks on every protected request. Negative/noninteger values fail startup.

The provider must support authorization code flow, signed ID Tokens, UserInfo,
and token introspection advertised as ``introspection_endpoint`` in discovery.
Token responses must include ``token_type=Bearer`` and a positive integer
``expires_in`` in seconds. Use ``openid email profile`` scopes. Fresh credential verification additionally
requires ``prompt=login``, ``max_age=0`` and a recent ID Token ``auth_time``.
A provider without introspection is refused with a configuration message;
expiry-only fallback is not supported. No blanket compatibility with providers
that lack these capabilities is implied.

For Keycloak, use a confidential client with Standard Flow, the callback above,
and email/profile scopes. Enable Direct Access Grants only if you need IdP
password authentication for mail clients. No post-logout callback is required:
Mailu does not terminate the provider's SSO session.

Identity and credentials
------------------------

Mailu trusts the configured provider's email, normalizes it using Mailu's email
rules, and matches that email to the local account. ``email_verified=true`` is
not required. No persistent issuer/subject account link or database migration is
introduced. Administrators must control email reassignment at the trusted IdP.
Protocol issuer, audience, signature, expiry, nonce and ID Token/UserInfo subject
agreement are still verified before login.

Email/password authentication checks the local password first. A successful
local password is never sent to the IdP. On mismatch or absence of a usable local
password, OIDC-enabled installations can try the IdP's password grant and verify
UserInfo against the requested account. A browser session never authenticates a
submitted password. An independent local login clears previous OIDC state.

External SMTP/IMAP clients use their supplied password or Mailu application token;
they do not inherit a browser OIDC login. Passwordless local users can use the
IdP password grant if the provider permits it, or create an application token
through fresh browser verification. Existing ``AUTH_REQUIRE_TOKENS``, protocol
flags, token IP restrictions and rate limits continue to apply. Mail protocol
password checks never create users or browser sessions.

Accounts and provisioning
-------------------------

By default an existing Mailu user is required. With ``OIDC_AUTH_CREATE=true``,
only a successful normal browser login may create an ordinary user in an existing
domain. Domains are never created. Existing account privileges remain unchanged;
IdP roles/groups do not grant Mailu administrator rights. Disabled users are
never reenabled by OIDC. Domain user limits, configured default quota and domain
mailbox quota limits apply; existing users can still log in at capacity.

Automatically created users have an unusable local password marker, not a shared
or distributed temporary password. Administrators may set a password under their
existing scoped permissions; the user can initialize it with fresh OIDC verification.

Mailu-disabled or deleted accounts lose protected Web access and their session
on the next request. Disabled accounts cannot perform new local, OIDC or
application-token authentication. Established SMTP/IMAP connections are not
forcibly disconnected. IdP rejection/revocation affects OIDC authentication and
OIDC-origin sessions, while independent local passwords/sessions and application
tokens remain usable.

Expiry, revocation and provider outages
---------------------------------------

Positive introspection applies even while an access token is locally unexpired.
An explicitly inactive unexpired token ends the OIDC session without trying to
refresh around revocation. Normal expiration may refresh; absent or refused
refresh credentials end the session. A rotated refresh token replaces the old
one; an omitted refresh token preserves it.

Discovery is lazy with a five-second HTTP timeout, ten-second failure backoff and
five-minute metadata cache. Initialization failures do not change ``OIDC_ENABLED``.
Locally validated passwords and application tokens do not wait for discovery.

A still-valid positive cache entry permits access during an outage. Otherwise
network/provider-server failures temporarily refuse protected access while
retaining the OIDC session and tokens for recovery. Direct admin UI requests
return HTTP 503; internal Nginx auth-request authorization returns HTTP 403 so
existing front handling shows the login screen instead of producing a 500.
Login, fresh verification and logout remain available. Existing Mailu session
and absolute lifetime settings still apply. Legacy sessions from the earlier
OIDC patch must authenticate again after this change.

Fresh verification for credential operations
--------------------------------------------

Application-token creation requires the acting user's current local password or
fresh browser OIDC verification. Initial self-service local-password setup
requires fresh OIDC verification; subsequent self-service password changes allow
either alternative. This applies to the actual POST, including forced password
changes. An existing browser login or IdP password grant alone is insufficient.
This verification also applies when OIDC is disabled. Header-proxy users with
an unknown, automatically generated password need an administrator to set a
known local password, or a matching OIDC identity for fresh verification.
Scoped administrator password-setting rights and management APIs authenticated
with ``API_TOKEN`` retain their existing authorization boundary.

Choose the OIDC verification link on the credential form, confirm the verification
request, authenticate again at the provider, then return and submit the operation.
Enter the new password and token details after returning; passwords are not
stored for callback replay. CSRF and password-quality/rate-limit checks remain
in effect. Delegated token creation verifies the acting administrator, not the
target user's password.

Authorization transactions expire after five minutes and are bound to the initiating
server-side session, exact redirect URI, nonce and purpose. Credential proofs
expire after two minutes and are bound to session, acting user, operation and
target. They are consumed once on successful completion. Starting another
verification replaces the pending one. Callback/proof consumption is atomic in
Redis and does not depend on a particular worker's mutable grant dictionary.
Cancellation, malformed callbacks and replay fail without automatic redirect loops.

Logout
------

Mailu logout clears its Web session and OIDC credentials and preserves existing
Webmail cookie cleanup. It leaves IdP SSO logged in, application tokens valid,
and established mail connections running. A later normal OIDC login may reuse
the provider's SSO session; credential operations still require fresh verification.

Library and regression checks
-----------------------------

The latest stable ``oic`` (PyOIDC) release checked on 2026-11-07 is ``1.7.0``:
https://pypi.org/project/oic/ and https://github.com/CZ-NIC/pyoidc/releases/latest .
The production pin already uses this version. Development and focused tests pin
the same release and assert the imported distribution version. Unreleased master
is not used. Tests exercise the real Flask app and PyOIDC parsing/signatures with
an isolated SQLite database, session/limiter storage and deterministic fake IdP.
MySQL/PostgreSQL integration and production IdP/mail-stack e2e are not covered
by this focused SQLite suite. Run without publishing images::

    docker build -t mailu-oidc-tests -f tests/oidc/Dockerfile .
    docker run --rm mailu-oidc-tests

日本語: OIDC の設定と動作
-------------------------

このページを、この fork の OIDC 設定と動作の唯一の参照先とする。
同じアカウントで OIDC とローカルパスワードを併用できる。
修正範囲は admin アプリケーションであり、front、Dovecot、Postfix の OIDC 修正は不要。

設定と IdP の要件
`````````````````

``OIDC_ENABLED=true`` とクライアント ID・secret を設定する。
``OIDC_PROVIDER_INFO_URL`` は issuer URL とし、discovery の末尾は付けない。
既定の ``https://localhost/info`` は仮の値なので、実際の issuer を指定する。
``OIDC_REDIRECT_HOST`` は公開ホスト名と任意のポート番号とし、scheme や path は付けない。
IdP に ``https://<OIDC_REDIRECT_HOST>/sso/login/oidc`` を正確に登録する。
ボタン名は ``OIDC_BUTTON_NAME`` で指定する。

IdP には認可コードフロー、署名された ID Token、UserInfo と introspection が必要。
discovery に ``introspection_endpoint`` がない場合は、通信障害と区別して設定上の理由で拒否する。
期限だけによる暗黙のフォールバックは行わない。
トークン応答には ``token_type=Bearer`` と正整数秒の ``expires_in`` が必要。
スコープは ``openid email profile`` を使う。
メールクライアントで IdP のパスワードを使う場合だけ、IdP 側で password grant を許可する。

認証元とユーザーの信頼
``````````````````````

設定した IdP のメールアドレスを信頼し、Mailu の表記規則で正規化して既存アカウントと照合する。
``email_verified=true`` は要求しない。
``iss``・``sub`` による永続的な紐付けや、そのための DB 変更は追加しない。
IdP のメールアドレス変更・再割り当ては運用側で管理する。
これとは別に、issuer・audience・署名・期限・nonce・ID Token と UserInfo の sub 一致は検証する。

メールアドレスとパスワードの認証はローカル優先とする。
ローカルで成功したパスワードは IdP に送らない。
不一致または未設定の場合だけ、IdP の password grant を試す。
ブラウザーの認証済み状態で、入力されたパスワードの検証を代用しない。
独立したローカルログインは、古い OIDC 状態を破棄する。

SMTP・IMAP はブラウザーセッションを引き継がず、入力された資格情報を検証する。
ローカルパスワードがない場合も、IdP の password grant または Mailu アプリトークンを利用できる。
``AUTH_REQUIRE_TOKENS``、プロトコルの有効フラグ、トークンの IP 制限、レート制限は維持する。
メールプロトコルの認証によってユーザーを作成しない。

自動作成とアカウントの無効化
````````````````````````````

``OIDC_AUTH_CREATE`` は boolean、既定値は ``false``。
``PROXY_AUTH_CREATE`` とは独立した設定とする。
有効な場合、通常のブラウザー OIDC ログインだけが既存ドメイン内の一般ユーザーを作成する。
ドメインの作成、管理権限の割り当て、無効ユーザーの再有効化は行わない。
既存ユーザーの権限は維持する。
ユーザー数の上限、既定容量、ドメインのメールボックス容量制限は通常と同じ設定を適用する。
上限に達していても、既存ユーザーはログインできる。
自動作成ユーザーに利用可能な仮パスワードは配布しない。

Mailu で無効化・削除されたユーザーは、次の保護対象 Web リクエストで拒否され、セッションを破棄する。
無効ユーザーの新規認証は、ローカル・OIDC・アプリトークンのいずれも拒否する。
接続済みの SMTP・IMAP は強制切断しない。
IdP 側の拒否・失効は OIDC 認証と OIDC 起源セッションに作用し、
独立したローカルパスワード・セッションとアプリトークンは維持する。

失効・期限・通信障害
````````````````````

``OIDC_INTROSPECTION_CACHE_TTL`` は非負整数の秒数で、既定値は 30。
0 は成功結果のキャッシュを無効にし、負値・整数以外は起動時に拒否する。
成功結果はセッションごとに保存し、アクセストークンの期限を超えて保持しない。
期限内のトークンもキャッシュ期限後に再確認する。
明示的な無効応答はセッションを終了し、refresh で迂回しない。
通常の期限切れは refresh があれば更新し、不在・明示的拒否は終了する。
更新応答に refresh token がなければ旧値を維持し、あれば置き換える。

初期化は遅延実行し、HTTP timeout は 5 秒、失敗時の再試行待ちは 10 秒、
metadata のキャッシュは 5 分とする。
初期化障害で ``OIDC_ENABLED`` の設定を書き換えない。
ローカルで検証可能なパスワードやアプリトークンは、IdP 初期化を待たない。

通信障害中は有効な成功キャッシュがある場合だけ保護対象にアクセスできる。
それ以外は一時拒否とし、セッション・トークンを保持して復旧を待つ。
admin 画面は HTTP 503、Nginx の内部認可は既存契約に合わせて HTTP 403 を返す。
ログイン画面・再認証・ログアウトは利用できる。
既存の Mailu セッション有効期間は延長しない。
旧パッチ形式の OIDC セッションは、この変更後に再ログインが必要。

パスワードとアプリトークンの本人確認
````````````````````````````````````

本人によるアプリトークン発行には、現在のローカルパスワードまたは新たな OIDC 再認証を要求する。
ローカルパスワードの初回設定は OIDC 再認証、設定後の本人変更はそのどちらかを要求する。
両方は要求しない。
OIDC 無効時もこの本人確認を適用する。
自動生成パスワードを知らないヘッダープロキシ利用者は、管理者による既知のローカルパスワード設定か、
同じメールアドレスの OIDC アカウントでの再認証が必要になる。
強制パスワード変更を含む実際の POST に適用し、既存セッションや password grant だけでは許可しない。
既存の管理権限によるパスワード設定と、``API_TOKEN`` を使う管理 API の境界は維持する。
代理操作の本人確認は操作する管理者を対象とし、対象ユーザーの資格情報は使わない。

資格情報フォームの OIDC 再認証リンクを選び、確認画面から IdP で認証し直し、戻って操作を送信する。
新しいパスワードやトークンの詳細は、戻ってから入力する。
パスワードを URL や callback 用の再実行データに保存しない。
CSRF、パスワード品質、ローカルパスワードのレート制限は維持する。

再認証は ``prompt=login``・``max_age=0`` を要求し、最近の ``auth_time`` と操作ユーザーの一致を確認する。
認可トランザクションは 5 分、操作証明は 2 分で失効する。
セッション、ユーザー、操作目的、対象に紐付け、成功した操作に一度だけ使う。
並列 callback の消費は Redis 上で原子的に行い、worker 固有の grant 辞書に依存しない。
取消・不正応答・再送は、500 や自動再認証ループにせず拒否する。

ログアウトと検証
````````````````

Mailu の Web セッション・OIDC トークンを破棄し、Webmail cookie の後処理を維持する。
IdP の SSO 状態、Mailu アプリトークン、接続済み SMTP・IMAP は維持する。

2026-11-07 に確認した ``oic`` の最新安定版は 1.7.0 で、本番の既存 pin と一致する。
開発・テストも同じ版に固定し、実際に import した配布物の版とプロトコルの動作を回帰テストで検証する。
上記の Docker コマンドは公開・本番 IdP 接続を伴わない。

この SQLite テストには、MySQL・PostgreSQL、本番 IdP、メールスタック全体の e2e は含まない。
