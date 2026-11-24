"""Drive cmapi's KeycloakAdminDirectory against a live Keycloak, the way core/context.py builds it, and print each request
as it goes on the wire: method, the raw request target (httpx.URL(url).raw_path, the bytes httpx writes on the request
line) and Keycloak's status. Then the result of each lookup. Reads the client secret from CMAPI_DIR_SECRET only.

Usage: drive_directory.py ISSUER   (with PYTHONPATH naming the cmapi source under test)
"""
from __future__ import annotations

import os
import sys

import httpx

from cmapi.core import context
from cmapi.core.identity import keycloak_admin
from cmapi.core.identity.keycloak_admin import KeycloakAdminDirectory

issuer = sys.argv[1]
if hasattr(keycloak_admin, "split_issuer"):          # after #640: context.py calls split_issuer
    base, realm = keycloak_admin.split_issuer(issuer)
    how = "split_issuer(issuer)"
else:                                                # before #640: core/context.py lines 150-151, verbatim
    realm = issuer.rsplit("/realms/", 1)[1]
    base = issuer.rsplit("/realms/", 1)[0]
    how = 'issuer.rsplit("/realms/", 1)'
print(f"  realm from {how}: {realm!r}")

real = context._http_for_directory(True)


def http(method, url, headers, form):
    status, body = real(method, url, headers, form)
    print(f"  {method:4} {httpx.URL(url).raw_path.decode()} -> {status}")
    return status, body


d = KeycloakAdminDirectory(base, realm, "cmapi-directory", os.environ["CMAPI_DIR_SECRET"], http)
for label, call in (("get_user('ola')", lambda: d.get_user("ola")),
                    ("find_by_employee_id('1001')", lambda: d.find_by_employee_id("1001")),
                    ("search('ola')", lambda: d.search("ola"))):
    try:
        got = call()
        shown = [p.username for p in got] if isinstance(got, list) else (got.username if got else None)
        print(f"  {label} = {shown!r}")
    except Exception as exc:                          # noqa: BLE001 - the proof prints whatever the lookup raised
        print(f"  {label} raised {type(exc).__name__}: {exc}")
