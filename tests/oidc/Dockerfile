# Reuse upstream's production Mailu Python dependencies; never publish this image.
FROM ghcr.io/mailu/admin:2024.06.54@sha256:24134e7d959b9a3769476611ac3e29832ed96cf6ec3774188734bc29256cbe03
COPY tests/oidc/requirements.txt /tmp/oidc-requirements.txt
RUN /app/venv/bin/pip install --no-cache-dir -r /tmp/oidc-requirements.txt
COPY core/admin /app
COPY core/base/libs/socrate/socrate/web.py /tests/support/socrate/web.py
RUN cp /tests/support/socrate/web.py "$(/app/venv/bin/python -c 'import socrate; print(next(iter(socrate.__path__)))')/web.py"
COPY tests/oidc /tests/oidc
COPY core/base/requirements-prod.txt core/base/requirements-dev.txt /tests/dependencies/
COPY docs/oidc.rst /tests/oidc.rst
COPY core/nginx/conf/nginx.conf /tests/templates/front.conf
COPY webmails/nginx-webmail.conf /tests/templates/webmail.conf
COPY webmails/roundcube/config/config.inc.php /tests/templates/roundcube.php
COPY webmails/snappymail/defaults/application.ini /tests/templates/snappymail.ini
WORKDIR /app
ENV PYTHONPATH=/app
ENTRYPOINT ["/app/venv/bin/python", "-m", "unittest", "discover", "-s", "/tests/oidc", "-v"]
