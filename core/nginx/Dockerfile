# syntax=docker/dockerfile-upstream:1.4.3

# build static assets (intermediate)
FROM base as static

COPY static/ /static/

RUN set -euxo pipefail \
  ; gzip -k9 /static/*.ico /static/*.txt \
  ; chmod a+rX-w -R /static


# nginx image
FROM base

ARG VERSION
LABEL version=$VERSION

# Dovecot 2.3 requires ICU 74 from the same tagged repository.
# Alpine 3.21 regular support ended on 2026-11-01. Dovecot 2.3 and ICU 74
# retain known security risks until the front proxy can move off these packages.
# Upstream discussion: https://github.com/Mailu/Mailu/pull/4214#issuecomment-7039588736
RUN set -euxo pipefail \
  ; printf '%s\n' '@legacy-dovecot https://dl-cdn.alpinelinux.org/alpine/v3.21/main' >> /etc/apk/repositories \
  ; apk add --no-cache certbot openssl py3-cryptography py3-requests py3-watchdog \
    'nginx>=1.28.3-r8' 'nginx-mod-http-brotli>=1.28.3-r8' 'nginx-mod-mail>=1.28.3-r8' \
    'dovecot@legacy-dovecot<2.4' 'dovecot-lmtpd@legacy-dovecot<2.4' \
    'dovecot-lua@legacy-dovecot<2.4' 'dovecot-pigeonhole-plugin@legacy-dovecot<2.4' \
    'dovecot-pop3d@legacy-dovecot<2.4' 'dovecot-submissiond@legacy-dovecot<2.4'

COPY conf/ /conf/
COPY --from=static /static/ /static/
COPY *.py /
COPY dovecot/proxy.conf dovecot/login.lua /dovecot_conf/

RUN echo $VERSION >/version

EXPOSE 80/tcp 443/tcp 110/tcp 143/tcp 465/tcp 587/tcp 993/tcp 995/tcp 25/tcp 4190/tcp
# EXPOSE 10025/tcp 10143/tcp 14190/tcp
HEALTHCHECK --start-period=60s CMD curl -m3 -skfLo /dev/null http://127.0.0.1:10204/health && kill -0 `cat /run/dovecot/master.pid`

VOLUME ["/certs", "/overrides"]

CMD /start.py
