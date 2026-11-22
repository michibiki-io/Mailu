"""Use normal mail clients and a cookie-aware HTTPS client on the test network."""
import imaplib
import os
import socket
import smtplib
import ssl
from urllib.parse import parse_qs, urlsplit

import requests

HOST = "mail.example.org"
ORIGIN = "https://" + HOST
EMAIL = "alice@example.org"
PREFIX = os.environ["WEB_BASE_PATH"]
MAILBOX = PREFIX + "/webmail/"
CA = "/certs/cert.pem"


def mail():
    tls = ssl.create_default_context(cafile=CA)
    with smtplib.SMTP(HOST, 25, timeout=10) as smtp:
        smtp.ehlo()
        smtp.starttls(context=tls)
        assert not smtp.sendmail(
            "sender@example.org", [EMAIL], "Subject: Native image smoke\r\n\r\nMailu fixture message\r\n"
        )
    with imaplib.IMAP4_SSL(HOST, 993, ssl_context=tls, timeout=10) as imap:
        imap.login(EMAIL, "fixture-only-password")
        assert imap.select("INBOX", readonly=True) == ("OK", [b"1"])
        status, message = imap.fetch("1", "(BODY.PEEK[TEXT])")
        assert status == "OK" and b"Mailu fixture message" in message[0][1], message
    print("SMTP STARTTLS delivery and authenticated IMAPS retrieval passed")


def web():
    tls = ssl.create_default_context(cafile=CA)
    tls.set_alpn_protocols(["h2", "http/1.1"])
    with socket.create_connection((HOST, 443), timeout=10) as connection:
        with tls.wrap_socket(connection, server_hostname=HOST) as https:
            assert https.selected_alpn_protocol() == "http/1.1"

    with requests.Session() as browser:
        browser.verify = CA
        browser.trust_env = False

        def get(target, status, **kwargs):
            url = target if target.startswith("https://") else ORIGIN + target
            response = browser.get(url, timeout=10, allow_redirects=False, **kwargs)
            assert response.status_code == status, (response.url, response.status_code, response.text[:300])
            return response

        if PREFIX:
            redirect = get(PREFIX, 308)
            assert redirect.headers["Location"] == PREFIX + "/", redirect.headers
            get("/sso/login", 404)
        login = get(MAILBOX, 302).headers["Location"]
        assert urlsplit(login).path == PREFIX + "/sso/login", login
        assert parse_qs(urlsplit(login).query)["url"] == [MAILBOX], login
        assert "OpenID Connect" in get(login, 200).text

        authorization = get(PREFIX + "/sso/oidc/start", 302, params={"url": MAILBOX})
        provider = authorization.headers["Location"]
        assert urlsplit(provider).netloc == "idp:8443", provider
        assert parse_qs(urlsplit(provider).query)["redirect_uri"] == [
            ORIGIN + PREFIX + "/sso/login/oidc"
        ], provider
        callback = get(provider, 302).headers["Location"]
        completed = get(callback, 302)
        assert completed.headers["Location"] == ORIGIN + MAILBOX, completed.headers
        assert any(cookie.secure and cookie.path == (PREFIX or "/") and cookie.name == "session"
                   for cookie in browser.cookies), browser.cookies
        get(PREFIX + "/admin/user/settings", 200)
        get(PREFIX + "/static/mailu.png", 200)

        sso = get(MAILBOX, 302).headers["Location"]
        assert sso == "sso.php", sso
        index = get(MAILBOX + sso, 302).headers["Location"]
        assert index == "index.php", index
        assert "Mailu Webmail" in get(MAILBOX + index, 200).text
        assert any(cookie.name == "roundcube_sessauth" for cookie in browser.cookies), browser.cookies
        get("https://idp:8443/checked", 200)
        logout = get(PREFIX + "/sso/logout", 302)
        assert urlsplit(logout.headers["Location"]).path == PREFIX + "/sso/login", logout.headers
        get(MAILBOX, 302)
    print(f"OIDC callback, Cookie Path, introspection, Roundcube SSO and logout passed at {PREFIX or '/'}")


if __name__ == "__main__":
    mail()
    web()
