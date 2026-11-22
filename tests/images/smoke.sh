#!/usr/bin/env bash
set -euo pipefail

export SMOKE_TLS_DIR
SMOKE_TLS_DIR=$(mktemp -d)
chmod 755 "$SMOKE_TLS_DIR"
project="mailu-smoke-$$"
compose=(docker compose -f tests/images/compose.yaml -p "$project")

cleanup() {
    local status=$?
    if (( status != 0 )); then
        "${compose[@]}" logs --no-color || true
    fi
    "${compose[@]}" down -v || true
    rm -rf "$SMOKE_TLS_DIR"
}
trap cleanup EXIT

openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -subj '/CN=mail.example.org' -addext 'subjectAltName=DNS:mail.example.org,DNS:idp' \
    -keyout "$SMOKE_TLS_DIR/key.pem" -out "$SMOKE_TLS_DIR/cert.pem"

exec_in() {
    "${compose[@]}" exec -T "$@"
}

# Read the installed package versions and compare with Alpine's version rules.
run_image() {
    local image=$1
    shift
    docker run --rm -i --network none --entrypoint /bin/sh "mailu-test/mailu-$image:local" "$@"
}

for image in nginx admin webmail; do
    platform=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "mailu-test/mailu-$image:local")
    test "$platform" = "linux/${ARCH#linux/}"
    echo "$image $platform"
    run_image "$image" -ec '
        cat /etc/alpine-release
        apk --print-arch
        for executable in nginx php php-fpm84; do
            if command -v "$executable" >/dev/null; then
                "$executable" -v
            fi
        done
    '
done

run_image nginx -es <<'APK'
test "$(cat /etc/alpine-release)" = 3.22.8
packages=$(apk info -v)
for package in nginx nginx-mod-mail nginx-mod-http-brotli; do
    installed=$(printf '%s\n' "$packages" | sed -n "s/^$package-\([0-9].*\)$/\1/p")
    echo "$package $installed"
    test -n "$installed"
    test "$(apk version -t "$installed" 1.28.3-r8)" != '<'
done
dovecot --version | grep '^2\.3\.'
for package in dovecot dovecot-lmtpd dovecot-lua dovecot-pigeonhole-plugin dovecot-pop3d dovecot-submissiond; do
    printf '%s\n' "$packages" | grep "^$package-2\.3\."
done
for package in icu-data-en icu-libs; do
    printf '%s\n' "$packages" | grep "^$package-74\."
done
APK

run_image webmail -es <<'APK'
test "$(cat /etc/alpine-release)" = 3.24.3
packages=$(apk info -v)
for requirement in nginx:1.30.7-r0 php84:8.4.28-r0 php84-fpm:8.4.28-r0; do
    package=${requirement%:*}
    installed=$(printf '%s\n' "$packages" | sed -n "s/^$package-\([0-9].*\)$/\1/p")
    echo "$package $installed"
    test -n "$installed"
    test "$(apk version -t "$installed" "${requirement#*:}")" != '<'
done
test "$(readlink -f /usr/bin/php)" = /usr/bin/php84
APK

check_nginx() {
    local rendered
    rendered=$(exec_in "$1" nginx -T)
    printf '%s\n' "$rendered" | grep -E '^[[:space:]]*http2 off;'
    if printf '%s\n' "$rendered" | grep -Eq '^[[:space:]]*(http2[[:space:]]+on|listen[^;]*(http2|quic)|stream[[:space:]]*\{)'; then
        echo "Unexpected HTTP/2, HTTP/3 or stream configuration in $1" >&2
        return 1
    fi
}

check_webmail() {
    local document_root=$1
    check_nginx webmail
    exec_in webmail php-fpm84 -tt
    test "$(exec_in webmail curl -fsS http://127.0.0.1/ping)" = pong
    "${compose[@]}" cp tests/images/webmail.php "webmail:$document_root/mailu-ci.php"
    exec_in webmail chmod 444 "$document_root/mailu-ci.php"
    exec_in --user mailu webmail php "$document_root/mailu-ci.php" | grep '^cli PHP 8\.4\.'
    exec_in webmail curl -fsS -H 'Host: mail.example.org' http://127.0.0.1/mailu-ci.php | grep '^fpm-fcgi PHP 8\.4\.'
    exec_in webmail rm "$document_root/mailu-ci.php"
}

export WEB_BASE_PATH WEBMAIL
WEBMAIL=roundcube
for WEB_BASE_PATH in '' /mailu; do
    "${compose[@]}" up -d --wait --wait-timeout 120
    check_nginx front
    exec_in front doveconf -c /etc/dovecot/proxy.conf -n >/dev/null
    exec_in front sh -ec 'kill -0 "$(cat /run/dovecot/master.pid)"'
    check_webmail /var/www/roundcube/public_html
    exec_in webmail test -s /data/roundcube.db
    exec_in front python3 /test/proxy.py
    "${compose[@]}" down -v
done

WEB_BASE_PATH=
WEBMAIL=snappymail
"${compose[@]}" up -d --wait --wait-timeout 120 webmail
check_webmail /var/www/snappymail
exec_in webmail test -d /var/www/snappymail/snappymail/v/3.0.0
page=$(exec_in webmail curl -fsS -H 'Host: mail.example.org' http://127.0.0.1/)
grep -qi snappymail <<< "$page"
echo "SnappyMail 3.0.0 returned its page through NGINX and FPM"
