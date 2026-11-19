"""Public HTTP paths shared by the three Mailu web containers."""

import os
import re


_PATH = re.compile(r"(?:/[A-Za-z0-9_-]+)+")
_ROOT_ENDPOINTS = {"health", "internal", "mobileconfig", "webdav"}


def base_path():
    path = os.environ.get("WEB_BASE_PATH", "")
    if path and (not _PATH.fullmatch(path) or path.split("/")[1].lower() in _ROOT_ENDPOINTS):
        raise ValueError("WEB_BASE_PATH must be an absolute URL path with no trailing slash "
                         "or reserved first segment")
    return path


def mount_paths(config, prefix):
    config["WEB_BASE_PATH"] = prefix
    if not prefix:
        return
    for name, default in (("WEB_ADMIN", "/admin"), ("WEB_WEBMAIL", "/webmail"),
                          ("WEB_API", "/api"), ("WEBROOT_REDIRECT", "")):
        value = config.get(name) or default
        if name == "WEBROOT_REDIRECT" and value in ("", "none"):
            continue
        if value == "/" and name == "WEB_WEBMAIL":
            config[name] = prefix + "/"
            continue
        if not isinstance(value, str) or not _PATH.fullmatch(value.rstrip("/")):
            raise ValueError(f"{name} must be an absolute path within the Mailu mount")
        config[name] = prefix + (value if name == "WEBROOT_REDIRECT" else value.rstrip("/"))
