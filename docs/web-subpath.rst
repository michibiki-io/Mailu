Publishing the Web UI under a subpath
====================================

Set ``WEB_BASE_PATH=/mailu`` on the front, admin, and enabled webmail
containers. Use the same value in all three. An unset or empty value keeps
the default root deployment. Use slash-separated letters, digits, hyphens,
or underscores with no trailing slash. Paths used for internal auth, health,
and other root-level endpoints are reserved.

Keep ``WEB_ADMIN=/admin``, ``WEB_WEBMAIL=/webmail``, and ``WEB_API=/api``
or set custom paths relative to the mount. For example, ``WEB_ADMIN=/settings``
exposes ``/mailu/settings``. ``WEBROOT_REDIRECT=/webmail`` forwards
``/mailu/`` to the enabled Webmail application. An empty value gives a 404
fallback for unhandled paths and ``none`` leaves the entry point to a front
override. Requests to ``/mailu`` redirect to ``/mailu/``. When Webmail is
mounted directly at ``/``, it handles the mount's entry point as usual.

Register ``https://mail.example.org/mailu/sso/login/oidc`` at the identity
provider if OIDC is enabled. Keep ``OIDC_REDIRECT_HOST=mail.example.org``.
Restore ``https://mail.example.org/sso/login/oidc`` when rolling back to
a root deployment.

Helm
----

Use the official Mailu chart, version 2.8.0 in this example. Keep
``mailuVersion`` at the upstream base and override only the three images
from the same fork Release. The Helm snippet is an overlay for a working
installation with the release name or full name ``mailu``. Replace the host
and tags with the values for the deployment.

.. code-block:: yaml

   fullnameOverride: mailu
   hostnames: [mail.example.org]
   mailuVersion: "2024.06.71"
   front:
     image:
       repository: michibiki-io/mailu-nginx
       tag: "2024.06.71-r1"
     extraEnvVars:
       - {name: WEB_BASE_PATH, value: /mailu}
   admin:
     image:
       repository: michibiki-io/mailu-admin
       tag: "2024.06.71-r1"
     extraEnvVars:
       - {name: WEB_BASE_PATH, value: /mailu}
   webmail:
     enabled: true
     image:
       repository: michibiki-io/mailu-webmail
       tag: "2024.06.71-r1"
     extraEnvVars:
       - {name: WEB_BASE_PATH, value: /mailu}
   ingress:
     enabled: true
     path: /mailu
     pathType: Prefix
     extraPaths:
       - path: /mail/config-v1.1.xml
         pathType: Exact
         backend: &front {service: {name: mailu-front, port: {name: http}}}
       - path: /.well-known/autoconfig
         pathType: Prefix
         backend: *front
       - path: /Autodiscover
         pathType: Prefix
         backend: *front
       - path: /autodiscover
         pathType: Prefix
         backend: *front
       - path: /mobileconfig
         pathType: Exact
         backend: *front
       - path: /apple.mobileconfig
         pathType: Exact
         backend: *front
       # Include these three paths when WebDAV is enabled.
       - path: /webdav
         pathType: Prefix
         backend: *front
       - path: /.well-known/carddav
         pathType: Exact
         backend: *front
       - path: /.well-known/caldav
         pathType: Exact
         backend: *front

Forward the request path intact. If Mailu performs HTTP-01 validation,
also forward ``/.well-known/acme-challenge/`` to front under the required
challenge hostnames. Use ``helm template`` to confirm the Ingress routes to
the chart's front Service and all three workloads use the expected images
and environment variable.

Docker Compose
--------------

Pass the same ``WEB_BASE_PATH`` value through ``mailu.env`` and override the
``front``, ``admin``, and ``webmail`` service images with the three
fixed images from the Release. The following paths can coexist with another
app at the origin root. Forward the original request URI and preserve the
external host and HTTPS scheme using the existing trusted-proxy settings.

.. code-block:: nginx

   location = /mailu { include mailu-http-proxy.conf; }
   location /mailu/ { include mailu-http-proxy.conf; }
   location = /mail/config-v1.1.xml { include mailu-http-proxy.conf; }
   location ^~ /.well-known/autoconfig/ { include mailu-http-proxy.conf; }
   location ~* ^/autodiscover/ { include mailu-http-proxy.conf; }
   location ~ ^/(apple\.)?mobileconfig$ { include mailu-http-proxy.conf; }
   # Include when WebDAV is enabled.
   location ~ ^/(webdav(/|$)|\.well-known/(carddav|caldav)$) {
       include mailu-http-proxy.conf;
   }

Use this file as ``mailu-http-proxy.conf`` in an HTTPS server block, with a
``mailu_front`` upstream pointing to the front container's HTTP port.
See :doc:`reverse` for the proxy trust settings. If Mailu performs HTTP-01
validation, forward ``/.well-known/acme-challenge/`` to front separately on
the required hostnames.

.. code-block:: nginx

   proxy_pass http://mailu_front;
   proxy_set_header Host $http_host;
   proxy_set_header X-Forwarded-Proto $scheme;
   proxy_set_header X-Real-IP $remote_addr;

Rollback
--------

Restore the previous three image references, the matching upstream version,
and the previous Ingress or proxy routes and environment. Restore the previous
OIDC callback registration if applicable. Clients still use the same URLs
for root-level autoconfiguration and WebDAV.
