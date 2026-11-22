# syntax=docker/dockerfile-upstream:1.4.3

FROM base AS snuffleupagus

ARG SNUFFLEUPAGUS_VERSION=0.14.0
ARG SNUFFLEUPAGUS_SHA256=080cf7e24d15a8650e271837030fca546e627c7a4c7317710c683282fdcb71c6

RUN set -euxo pipefail \
  ; apk add --no-cache autoconf build-base pcre2-dev re2c 'php84-dev>=8.4.28-r0' \
  ; curl -fsSL "https://codeload.github.com/jvoisin/snuffleupagus/tar.gz/refs/tags/v${SNUFFLEUPAGUS_VERSION}" -o /tmp/snuffleupagus.tgz \
  ; printf '%s  %s\n' "${SNUFFLEUPAGUS_SHA256}" /tmp/snuffleupagus.tgz | sha256sum -c - \
  ; tar -xzf /tmp/snuffleupagus.tgz -C /tmp \
  ; cd "/tmp/snuffleupagus-${SNUFFLEUPAGUS_VERSION}/src" \
  ; phpize84 \
  ; ./configure --with-php-config=/usr/bin/php-config84 \
  ; make -j "$(grep -c processor /proc/cpuinfo)" \
  ; cp modules/snuffleupagus.so /tmp/

FROM base

ARG VERSION
LABEL version=$VERSION

COPY snappymail/pubkey.asc /tmp/snappymail.asc
COPY roundcube/pubkey.asc /tmp/roundcube.asc
COPY roundcube/roundcube.diff /tmp/roundcube.diff

# Roundcube database scripts use an unversioned PHP executable.
RUN set -euxo pipefail \
  ; apk add --no-cache \
    'nginx>=1.30.7-r0' gpg gpg-agent patch gd libsodium \
    aspell-uk aspell-ru aspell-fr aspell-de aspell-en \
    'php84>=8.4.28-r0' 'php84-fpm>=8.4.28-r0' php84-mbstring php84-zip php84-xml php84-simplexml php84-pecl-apcu \
    php84-dom php84-curl php84-exif php84-gd php84-iconv php84-intl php84-openssl php84-ctype \
    php84-pdo_sqlite php84-pdo_mysql php84-pdo_pgsql php84-pdo php84-sodium php84-tidy \
    php84-enchant enchant2-aspell php84-opcache php84-session php84-sockets php84-fileinfo php84-xmlreader php84-xmlwriter \
  ; ln -sf /usr/bin/php84 /usr/bin/php \
  ; rm /etc/nginx/http.d/default.conf \
  ; rm /etc/php84/php-fpm.d/www.conf \
  ; mkdir -m 700 /root/.gnupg/ \
  ; gpg --import /tmp/snappymail.asc \
  ; gpg --import /tmp/roundcube.asc \
  ; echo extension=snuffleupagus > /etc/php84/conf.d/snuffleupagus.ini \
  ; rm -f /tmp/roundcube.asc /tmp/snappymail.asc \
  ; mkdir -p /run/nginx /conf

# roundcube
ENV ROUNDCUBE_URL=https://github.com/roundcube/roundcubemail/releases/download/1.6.21/roundcubemail-1.6.21-complete.tar.gz
ENV CARDDAV_URL=https://github.com/mstilkerich/rcmcarddav/releases/download/v5.1.3/carddav-v5.1.3.tar.gz

RUN set -euxo pipefail \
  ; cd /var/www \
  ; curl -sLo /dev/shm/roundcube.tgz ${ROUNDCUBE_URL} \
  ; curl -sLo /dev/shm/roundcube.tgz.asc ${ROUNDCUBE_URL}.asc \
  ; gpg --status-fd 1 --verify /dev/shm/roundcube.tgz.asc /dev/shm/roundcube.tgz \
  ; tar xzf /dev/shm/roundcube.tgz \
  ; curl -sL ${CARDDAV_URL} | tar xz \
  ; mv roundcubemail-* roundcube \
  ; mkdir -p /var/www/roundcube/config \
  ; mv carddav roundcube/plugins/ \
  ; cd roundcube \
  ; rm -rf CHANGELOG.md SECURITY.md INSTALL LICENSE README.md UPGRADING composer.json-dist installer composer.* \
  ; ln -sf index.php /var/www/roundcube/public_html/sso.php \
  ; rm -rf plugins/{autologon,example_addressbook,http_authentication,krb_authentication,new_user_identity,password,redundant_attachments,squirrelmail_usercopy,userinfo,virtuser_file,virtuser_query} \
  ; patch -p0 < /tmp/roundcube.diff \
  ; rm /tmp/roundcube.diff

COPY roundcube/config/config.inc.php /conf/
COPY roundcube/login/ /var/www/roundcube/plugins/mailu/
COPY roundcube/config/config.inc.carddav.php /var/www/roundcube/plugins/carddav/config.inc.php

# snappymail

ENV SNAPPYMAIL_URL=https://github.com/the-djmaze/snappymail/releases/download/v3.0.0/snappymail-3.0.0.tar.gz

RUN set -euxo pipefail \
  ; mkdir  /var/www/snappymail \
  ; cd /var/www/snappymail \
  ; curl -sLo /dev/shm/snappymail.tgz  ${SNAPPYMAIL_URL} \
  ; curl -sLo /dev/shm/snappymail.tgz.asc  ${SNAPPYMAIL_URL}.asc \
  ; gpg --status-fd 1 --verify /dev/shm/snappymail.tgz.asc /dev/shm/snappymail.tgz \
  ; cat /dev/shm/snappymail.tgz | tar xz

# SnappyMail login
COPY snappymail/login/include.php /var/www/snappymail/
COPY snappymail/login/sso.php /var/www/snappymail/

# Parsed and moved at startup
COPY snappymail/defaults/application.ini /defaults/
COPY snappymail/defaults/default.json /defaults/

# set perms
RUN set -euxo pipefail \
  ; chmod -R a+rX /var/www/snappymail \
  ; chown -R root:root /var/www/snappymail \
  ; chown -R mailu:mailu /var/www/snappymail/data \
  ; chown -R root:root /var/www/roundcube/ \
  ; chown -R mailu:mailu /var/www/roundcube/temp /var/www/roundcube/logs \
  ; chmod -R a+rX /var/www/roundcube

# common
COPY --from=snuffleupagus /tmp/snuffleupagus.so /usr/lib/php84/modules/
COPY start.py /
COPY php.ini /defaults/
COPY php-webmail.conf /etc/php84/php-fpm.d/
COPY nginx-webmail.conf /conf/
COPY snuffleupagus.rules /etc/snuffleupagus.rules.tpl

# EXPOSE 80/tcp
VOLUME /data
VOLUME /overrides

CMD /start.py

HEALTHCHECK CMD test "$(curl -m3 -fsS http://127.0.0.1/ping)" = pong

RUN echo $VERSION >> /version
