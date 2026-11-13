# Second review: cmapi #184 / SEC-07

Review target: `head/` and `change.diff` only. Paths below are relative to this review folder. The export is not a Git repository. TokenSave context/status/read could not serve this unindexed export; inspection used source files directly. No container was started and no database was contacted. Primary-source receipts and executable checks are under `report/sources/` and `report/tests/`. Proposed fixes are under `report/fixes/`; the reviewed export stays intact.

The signature/type binding is sound. Proven defects are optional-scope migration (C5), CRC rollout order (C7), the missing-header test fixture (E1), and Helm dropping the legacy option (E2). C4 additionally identifies a **conditional V1-exchange configuration gap**, not a failure of the shipped ordinary grant flows. Every counted defect has a regression that fails against the export and passes against the proposed fixes. Server-side policy/rotation caveats are distinguished from these measured defects.

## C1 — CONFIRMED

The checked header belongs to the exact compact JWT whose signature is verified. `head/cmapi/src/cmapi/core/auth.py:152` reads `header = jwt.get_unverified_header(bearer)`. At `:165-166` the same local argument is passed to `jwt.decode(bearer, key.key, algorithms=["RS256"], audience=self.audience, issuer=self.issuer, leeway=self.leeway, options={"require": ["exp", "iat", "iss", "aud", "sub"]})`. Every decode exception at `:167-178` raises a `Problem`; the sole Identity return is `:186`, after the type check at `:180-185`. There is no signature-failure return path.

Installed PyJWT is **2.10.1**. Its [api_jws.py](https://github.com/jpadilla/pyjwt/blob/2.10.1/jwt/api_jws.py#L261-L297) constructs the signing input from the original encoded header and payload; its verification path at lines 209-220 verifies that input before returning the decoded structure. Its [api_jwt.py](https://github.com/jpadilla/pyjwt/blob/2.10.1/jwt/api_jwt.py#L132-L176) defaults signature verification to true and validates claims after JWS verification. Copies inspected locally are `report/sources/api_jws.py` and `api_jwt.py`.

The type check **may** run before signature verification as a cheap rejection of an obviously unsuitable token. An unverified header must never authorize acceptance. There is no security need to move the present check: acceptance still requires both signature and type. RFC 9068 §4 lists the type check first, but does not make a different execution order an authentication bypass. Checking early would change which rejection wins, avoid some signature/JWKS work, and could turn an otherwise unavailable-key 503 into a type 401. Checking late distinguishes a successfully verified, otherwise valid wrong-type token from a bad signature through its error detail/timing; it discloses no secret header or claim (those are already in the submitted token), nor any signing key. Public-key verification is itself public. Existing algorithm, key, expiry, audience and issuer error distinctions remain.

Evidence test: `report/tests/test_auth_review184.py::test_c1_changing_protected_header_without_resigning_never_returns_identity` changes only the protected header and keeps the signature. All three variants must fail with `401 / Invalid token`, including an apparently acceptable `at+jwt` header.

## C2 — CONFIRMED (for the specified token classes)

`head/cmapi/src/cmapi/core/auth.py:156` requires `header.get("alg") == "RS256"` and a key ID; `:165-166` pins the issuer, audience and required claims; `:180-185` says:

```python
header_type, claim_type = str(header.get("typ") or "").lower(), claims.get("typ")
rfc9068 = header_type in ACCESS_TOKEN_TYPES and claim_type in (None, "Bearer")
legacy = self.legacy_token_type and header_type == "jwt" and claim_type == "Bearer"
if not (rfc9068 or legacy):
    AUTH_FAILURES.labels("token-type").inc()
    raise Problem(401, "unauthenticated", "Token is not an access token")
```

`ACCESS_TOKEN_TYPES` at `:133` is `frozenset({"at+jwt", "application/at+jwt"})`. For otherwise valid RS256 tokens of the configured issuer/audience:

| Token/header | Result in default mode | Assessment |
|---|---|---|
| Keycloak ID token: `JWT`, claim `ID` | 401; normally audience validation already fails for a portal ID token; with cmapi audience it fails type validation | Correct |
| Refresh token signed HS512 | 401 unsupported algorithm, before key lookup | Correct |
| RS256 refresh-shaped token: `JWT`, claim `Refresh` | 401 type (assuming required claims and audience also pass) | Correct |
| `logout+jwt` | 401 type (a real logout token can fail audience/required claims earlier) | Correct |
| Header `typ` absent | 401 type, even if claim is `Bearer` | Correct |
| List, number, JSON null, dictionary | 401 type; their Python string forms cannot equal either allowed media type; null/falsy values become `""` | Correct; no coercion bypass |
| `at+jwt ` | 401 type | Correct: no whitespace trimming is required by this profile |
| `AT+JWT` | Accepted, with absent/`Bearer` claim | Correct: media type names are case insensitive |
| `application/at+jwt; charset=x` | 401 type | Correct: the profile permits the two specified values, not arbitrary media type parameters |

[RFC 9068 §4](https://www.rfc-editor.org/rfc/rfc9068.html#section-4) requires the two access-token media type spellings and rejection of other values. [RFC 7515 §4.1.9](https://www.rfc-editor.org/rfc/rfc7515.html#section-4.1.9) says: “all media type values, subtype values, and parameter names are case insensitive.” Its compact-media-type rule treats an omitted `application/` prefix as implicit. Thus accepting both spellings and ASCII case variants is right; the parameter-name rule does not require accepting added parameters. RFC 7515 makes `typ` optional for generic JWS; RFC 9068 makes it mandatory for this access-token profile.

This is not a proof against a malicious trusted issuer deliberately signing a different object as `at+jwt` with access-token claims. The security boundary includes the trusted issuer's correct typing. For actual Keycloak token classes, the distinction is supported by C3/C4. This change implements the type portion of RFC 9068; it does not claim to enforce every claim in the complete RFC profile.

Evidence tests: `report/tests/test_auth_review184.py` exercises real signed headers, including JSON null and genuinely absent `typ`, independently of the service fixture's omission bug discussed below.

## C3 — CONFIRMED

The **additional legacy branch**, not the whole authenticator, accepts only case-insensitive header `JWT` plus claim exactly `Bearer`: `head/cmapi/src/cmapi/core/auth.py:182`, quoted in C2. The RFC 9068 branch remains accepted with legacy mode enabled. `claims.get("typ") == "Bearer"` is false for an absent/null claim, `ID`, `Refresh`, and case variants of `Bearer`.

Keycloak 26.6.4 [TokenManager.generateIDToken](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/protocol/oidc/TokenManager.java#L1386-L1404) writes `idToken.type(TokenUtil.TOKEN_TYPE_ID);` and `idToken.audience(client.getClientId());`. [TokenUtil](https://github.com/keycloak/keycloak/blob/26.6.4/core/src/main/java/org/keycloak/util/TokenUtil.java#L41-L59) defines `TOKEN_TYPE_ID = "ID"` and `TOKEN_TYPE_BEARER = "Bearer"`. Consequently a normal ID token for `cmapi-docs` has audience `cmapi-docs`, not `cmapi-nonprod`, and claim `typ: ID`, not `Bearer`. The realm's audience mapper is access-token-only (CRC import `:200-206`; chart `head/deploy/helm/cmapi/templates/keycloak-realm.yaml:34-36`). Custom ID-token mappers can add audiences, so audience alone should not replace the exact legacy claim check.

No additional Keycloak-specific discriminator is necessary to distinguish these stock ID/refresh tokens: the exact `Bearer` claim plus the existing signature, issuer, audience, expiry and required-claim checks do that. Requiring `azp` to equal the resource audience would incorrectly reject normal access tokens issued to portal/docs/CLI clients. An allowlist of issuing clients could be a separate policy but is not needed to repair a demonstrated token-confusion bug here. [RFC 8725 §3.12](https://www.rfc-editor.org/rfc/rfc8725.html#section-3.12) permits mutually exclusive required claim values as a discrimination strategy. Legacy mode is an explicit compatibility exception to RFC 9068's header rule, not strict RFC 9068 conformance.

Evidence test: `report/tests/test_auth_review184.py::test_c3_legacy_requires_bearer` covers `JWT`, `jwt`, `JwT`, and absent/null/ID/Refresh/lowercase/uppercase claim alternatives.

## C4 — REFUTED as an unconditional coverage claim; emission rule CONFIRMED

**Conditional compatibility gap, not a demonstrated bypass or a failure of the shipped ordinary grants.** The decisive client is the client in Keycloak's session context at encoding time. It is not necessarily the client named by the token's `azp`, and the audience resource does not normally decide it.

Keycloak 26.6.4 [DefaultTokenManager.type, lines 244-255](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/jose/jws/DefaultTokenManager.java#L244-L255), ACCESS branch:

```java
ClientModel client = session.getContext().getClient();
return client != null && OIDCAdvancedConfigWrapper.fromClientModel(client).isUseRfc9068AccessTokenHeaderType()
    ? TokenUtil.TOKEN_TYPE_JWT_ACCESS_TOKEN
    : "JWT";
```

The constant is `at+jwt` ([TokenUtil:49](https://github.com/keycloak/keycloak/blob/26.6.4/core/src/main/java/org/keycloak/util/TokenUtil.java#L49)). The LOGOUT branch uses `logout+jwt`, and other categories default to `JWT`. Thus the new prose saying every token otherwise has `JWT` is an oversimplification for logout tokens.

[OIDCAdvancedConfigWrapper.isUseRfc9068AccessTokenHeaderType, lines 224-226](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/protocol/oidc/OIDCAdvancedConfigWrapper.java#L224-L226):

```java
public boolean isUseRfc9068AccessTokenHeaderType() {
    return Boolean.parseBoolean(getAttribute(USE_RFC9068_ACCESS_TOKEN_HEADER_TYPE, "false"));
}
```

[OIDCConfigAttributes:83](https://github.com/keycloak/keycloak/blob/26.6.4/server-spi-private/src/main/java/org/keycloak/protocol/oidc/OIDCConfigAttributes.java#L83) maps that constant to `access.token.header.type.rfc9068`. Java's boolean parser accepts case variants of the string `true`; absent/other strings mean false. This is the JOSE-header switch, separate from the payload token type.

| Grant | Client whose attribute decides | Source in tag 26.6.4 |
|---|---|---|
| Authorization code | Client redeeming its own code, e.g. `cmapi-docs` or `cmapi-portal` | [AuthorizationCodeGrantType:148-150,271](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/protocol/oidc/grants/AuthorizationCodeGrantType.java#L148-L150); common [OAuth2GrantTypeBase:117-123](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/protocol/oidc/grants/OAuth2GrantTypeBase.java#L117-L123) |
| Client credentials | Authenticated service client, e.g. `cmapi-automation` | [ClientCredentialsGrantType:147-148](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/protocol/oidc/grants/ClientCredentialsGrantType.java#L147-L148), same common builder |
| Device | Client associated with the approved device session, `cmapi-cli` | [DeviceGrantType:321-324,364](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/protocol/oidc/grants/device/DeviceGrantType.java#L321-L324), same common builder |
| Refresh | Client redeeming the refresh token; Keycloak checks it matches the token's client session. The attribute's current value applies to the newly encoded access token | [RefreshTokenGrantType:79-85](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/protocol/oidc/grants/RefreshTokenGrantType.java#L79-L85); [TokenManager:350-355](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/protocol/oidc/TokenManager.java#L350-L355) |
| Standard token exchange (V2) | Requesting client, not the subject token's client or target audience | [AbstractTokenExchangeProvider:273-275](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/protocol/oidc/tokenexchange/AbstractTokenExchangeProvider.java#L273-L275); [StandardTokenExchangeProvider:283-284](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/protocol/oidc/tokenexchange/StandardTokenExchangeProvider.java#L283-L284) |
| Legacy token exchange (V1), when enabled and authorized | First target audience client; token `azp` is then set back to the requester | [V1TokenExchangeProvider:306-313,334-339](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/protocol/oidc/tokenexchange/V1TokenExchangeProvider.java#L306-L339) |

V1 explicitly executes `session.getContext().setClient(targetClient);` and later `responseBuilder.getAccessToken().issuedFor(client.getClientId());`. Therefore **yes**, a token for cmapi can use a client the imports did not type. Both imports omit the attribute on the bearer-only API audience client: CRC `head/deploy/manifests/environments/crc/realm/10-realm-import.yaml:234-248` includes `bearerOnly: true` and `defaultClientScopes: ... cmapi-audience`, with no attributes; chart `head/deploy/helm/cmapi/templates/keycloak-realm.yaml:131-139` does the same. A permitted V1 exchange targeting this client produces a cmapi-audience token with header `JWT` until realm sync types the target. The API rejects it. Being bearer-only blocks authenticating *as* the API client, not exchanging *to* it.

The five shipped clients for ordinary grants all have the attribute: CRC `:249-346` and chart `:140-190` cover portal/docs/CLI/automation/payments. Neither import enables V1 exchange or grants exchange permissions; **the conditional V1 issue is not evidence of a currently usable exchange path on a default installation**. Hand-added clients with an optional audience scope are a separate concrete gap in C5; direct audience mappers or later exchange configuration also make scope-name selection an incomplete universal discovery method.

Reproduction is a configuration regression against both parsed CRC YAML and actual Helm output, not a live exchange. `report/tests/test_exchange_target_review184.py` fails twice on the export because the target attribute is absent; it passes twice with the fix. Keycloak's source establishes why that omission matters *when V1 is enabled*. Full replacement client entries and full test code follow in this section below.

Full replacement of the CRC API client entry:

```yaml
    - clientId: cmapi-nonprod
      name: cmapi nonprod API
      enabled: true
      publicClient: false
      bearerOnly: true
      attributes: {access.token.header.type.rfc9068: 'true'}
      standardFlowEnabled: false
      directAccessGrantsEnabled: false
      serviceAccountsEnabled: false
      defaultClientScopes:
      - basic
      - cmapi-identity
      - cmapi-audience
      - roles
      - profile
      - email
```

Full replacement of the chart API client entry:

```yaml
      - clientId: {{ $aud }}
        name: "cmapi {{ .Values.instance.name }} API"
        enabled: true
        publicClient: false
        bearerOnly: true
        attributes: {access.token.header.type.rfc9068: "true"}
        standardFlowEnabled: false
        directAccessGrantsEnabled: false
        serviceAccountsEnabled: false
        defaultClientScopes: [basic, cmapi-identity, cmapi-audience, roles, profile, email]
```

Full configuration regression (`report/tests/test_exchange_target_review184.py`):

```python
"""Configuration regression for Keycloak's V1 exchange target context.

V1 is optional and is not enabled by these manifests. If it is enabled, the
bearer-only API client is a valid target; its attribute controls the JOSE type.
"""
import os
from pathlib import Path
import subprocess

import pytest
import yaml


@pytest.mark.parametrize("deployment", ["crc", "helm"])
def test_exchange_target_uses_rfc9068_header(deployment):
    root = Path(os.environ.get("REVIEW184_HEAD", "head"))
    if deployment == "crc":
        text = (root / "deploy/manifests/environments/crc/realm/10-realm-import.yaml").read_text()
    else:
        text = subprocess.run(
            ["helm", "template", "review184", str(root / "deploy/helm/cmapi"),
             "-f", str(root / "deploy/environments/crc.yaml"),
             "--set", "keycloak.realmImport.enabled=true",
             "--set", "cmapi.digest=sha256:" + "a" * 64,
             "--set", "trustedCA.certificates=x"],
            check=True, text=True, capture_output=True,
        ).stdout
    realm = next(d["spec"]["realm"] for d in yaml.safe_load_all(text)
                 if d and d.get("kind") == "KeycloakRealmImport")
    target = next(c for c in realm["clients"] if c.get("bearerOnly"))
    assert "cmapi-audience" in target["defaultClientScopes"]
    assert (target.get("attributes") or {}).get("access.token.header.type.rfc9068") == "true", (
        f"V1 exchange uses target client {target['clientId']}, whose header defaults to JWT"
    )
```


## C5 — REFUTED: optional-scope callers are missed

**Concrete availability defect:** `head/cmapi/src/cmapi/tools/realm_sync.py:144` tests only `"cmapi-audience" in (c.get("defaultClientScopes") or [])`. A manually added client with `optionalClientScopes: [cmapi-audience]` can request `scope=cmapi-audience` and obtain the same audience mapper, yet the sync leaves its access-token header as `JWT`. Strict cmapi rejects that token. The function's own `:134-136` promise to converge clients added by hand is too broad.

This is not a missing field in the list API. Keycloak 26.6.4 [ClientsResource.getClients:125-129](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/services/resources/admin/ClientsResource.java#L125-L129) calls `ModelToRepresentation.toRepresentation(c, session)`. [ModelToRepresentation:903-904](https://github.com/keycloak/keycloak/blob/26.6.4/server-spi-private/src/main/java/org/keycloak/models/utils/ModelToRepresentation.java#L903-L904) explicitly sets **both** scope lists:

```java
rep.setDefaultClientScopes(new LinkedList<>(clientModel.getClientScopes(true).keySet()));
rep.setOptionalClientScopes(new LinkedList<>(clientModel.getClientScopes(false).keySet()));
```

[TokenManager.getRequestedClientScopes:725-743](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/protocol/oidc/TokenManager.java#L725-L743) resolves requested scope names against the client's optional scopes as well as always including default scopes. The CRC mapper at `head/deploy/manifests/environments/crc/realm/10-realm-import.yaml:200-206` writes `access.token.claim: 'true'`, `included.client.audience: cmapi-nonprod`, and `protocolMapper: oidc-audience-mapper`. Optional assignment changes when the scope is applied, not the mapper's resulting audience.

For selected clients, the Python update itself preserves representation fields: `realm_sync.py:145` uses `c["attributes"] = {**attributes, RFC9068_HEADER: "true"}` and `:146` PUTs `json=c`. Normal client attributes and active secret are not replaced by a newly invented representation or secret. The Keycloak representation includes attributes (`ModelToRepresentation:878`) and the existing confidential-client secret (`:896-900`). [ClientResource:845](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/services/resources/admin/ClientResource.java#L830-L847) applies `RepresentationToModel.updateClient`; [RepresentationToModel:542-546,579-595](https://github.com/keycloak/keycloak/blob/26.6.4/server-spi-private/src/main/java/org/keycloak/models/utils/RepresentationToModel.java#L579-L595) applies supplied attribute values and returns the supplied/current active secret rather than regenerating an existing one. The list's secret is not a `**********` mask in this source.

This is not an unconditional guarantee against server-side client-policy side effects: [ClientResource:158-175](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/services/resources/admin/ClientResource.java#L158-L175) triggers client policy hooks, and can clear secret-rotation metadata when its rotation-enabled flag remains false. [OIDCClientSecretConfigWrapper:78-88](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/protocol/oidc/OIDCClientSecretConfigWrapper.java#L78-L88) clears expiration and rotated-secret attributes. So **“each other attribute” cannot be guaranteed for arbitrary custom policy/rotation state**, even though the Python merge preserves every supplied field and the ordinary active secret is unchanged. No deployed rotation policy was inspected or exercised; this caveat is not counted as an additional proven defect of this change (the pre-existing password-grant sync already PUTs representations through the same endpoint).

Idempotence is confirmed for stable client state: after a successful update returns attribute string `"true"`, the condition at `:144` is false on subsequent runs. The function walks all pages (`:139`, `:148`) and terminates on an empty page. The no-network stub test verifies a later-page optional client, unrelated-client exclusion, exact preservation of the complete update body, and no second PUT. Separate default-scope coverage verifies pagination and idempotence on the original code as well.

Measured before: optional test fails with `realm.puts == []`; default-scope preservation/idempotence passes. After the replacement below: both pass. The fix includes the union of default and optional scope names; it does not pretend to discover arbitrary custom audience mappers or token-exchange policy.

Full replacement function (`report/fixes/access_token_type.py`; retain the existing module constant/imports):

```python
from cmapi.tools.realm_sync import RFC9068_HEADER, Realm


def access_token_type(rm: Realm) -> None:
    """Type tokens for clients with cmapi-audience as a default or optional scope."""
    changed, first = [], 0
    while True:
        clients = rm.get("/clients", params={"first": first, "max": 500}) or []
        if not clients:
            break
        for c in clients:
            attributes = c.get("attributes") or {}
            scopes = set(c.get("defaultClientScopes") or []) | set(c.get("optionalClientScopes") or [])
            if "cmapi-audience" in scopes and attributes.get(RFC9068_HEADER) != "true":
                c["attributes"] = {**attributes, RFC9068_HEADER: "true"}
                rm.call("PUT", f"/clients/{c['id']}", json=c)
                changed.append(c["clientId"])
        first += len(clients)
    print(f"access token type: at+jwt on each client of cmapi{' (changed: ' + ', '.join(sorted(changed)) + ')' if changed else ''}")
```

Full tests, including the stateful, paged admin stub (`report/tests/test_realm_sync_review184.py`):

```python
"""Exercise the real sync with paged, independent admin representations; no server."""
from copy import deepcopy

from cmapi.tools.realm_sync import RFC9068_HEADER, access_token_type


class RealmStub:
    def __init__(self, clients):
        self.clients = deepcopy(clients)
        self.puts = []

    def get(self, path, *, params):
        assert path == "/clients"
        first = params["first"]
        # A shorter page is allowed; the sync must still fetch the following page.
        return deepcopy(self.clients[first:first + 1])

    def call(self, method, path, *, json):
        assert method == "PUT"
        self.puts.append((path, deepcopy(json)))
        for index, client in enumerate(self.clients):
            if path == f"/clients/{client['id']}":
                self.clients[index] = deepcopy(json)
                return
        raise AssertionError(path)


def test_optional_cmapi_audience_is_typed_without_changing_other_fields():
    original = {
        "id": "optional-id", "clientId": "optional-pipeline",
        "defaultClientScopes": ["basic", "roles"],
        "optionalClientScopes": ["cmapi-audience"],
        "attributes": {"kept": "yes", "access.token.signed.response.alg": "RS256"},
        "secret": "existing-test-secret", "serviceAccountsEnabled": True,
    }
    realm = RealmStub([
        {"id": "unrelated", "clientId": "directory", "defaultClientScopes": ["basic"]},
        original,
    ])
    access_token_type(realm)
    expected = deepcopy(original)
    expected["attributes"][RFC9068_HEADER] = "true"
    assert realm.puts == [("/clients/optional-id", expected)]
    access_token_type(realm)
    assert realm.puts == [("/clients/optional-id", expected)], "second run must not PUT again"


def test_default_scope_pagination_preservation_and_idempotence():
    clients = [
        {"id": "one", "clientId": "docs", "defaultClientScopes": ["cmapi-audience"],
         "attributes": {"pkce.code.challenge.method": "S256"}},
        {"id": "two", "clientId": "automation", "defaultClientScopes": ["cmapi-audience"],
         "attributes": {"kept": "yes"}, "secret": "same-test-secret"},
        {"id": "three", "clientId": "already", "defaultClientScopes": ["cmapi-audience"],
         "attributes": {RFC9068_HEADER: "true"}},
    ]
    realm = RealmStub(clients)
    access_token_type(realm)
    assert len(realm.puts) == 2
    for original, updated in zip(clients[:2], realm.clients[:2]):
        expected = deepcopy(original)
        expected["attributes"][RFC9068_HEADER] = "true"
        assert updated == expected
    access_token_type(realm)
    assert len(realm.puts) == 2
```


## C6 — CONFIRMED for refusal causes; one new coverage defect

`head/cmapi/tests/service/conftest.py:60` now defaults `typ: str | None = "at+jwt"`; `:70-73` passes that header to `jwt.encode`. **There are no existing non-type refusal cases in the two requested files that now fail for the header type instead of their intended earlier cause. The requested list is empty.**

`head/cmapi/tests/service/test_review_b_auth.py:29-46` covers wrong audience, ID token for the portal, other issuer, trailing-slash issuer, expired token, future nbf, none/HS256/RS512 algorithms, wrong signing key, missing kid, missing exp/sub/iat, and ID/Refresh payload types. Header/algorithm/key failures happen at `auth.py:152-163`; signature and registered-claim failures happen at `:165-178`, all **before** the new type check. Its raw `jwt.encode` cases retain header `JWT`, but the missing-claim/portal-audience/algorithm failures still win. The final ID/Refresh payload cases use the new `at+jwt` fixture header and are refused for the intended payload type. `test_auth.py:28-61` has the same earlier-check ordering for its existing refusal cases. No test was weakened by a `JWT` header masking an intended signature or registered-claim rejection in the current implementation.

The tests mostly assert only status, so they are less robust to a future reordering. That is a test-strength observation, not a demonstrated false positive today. The reviewed `test_auth.py` passed 22 cases, `test_review_b_auth.py` passed 22, and the independent type/signature matrix passed 28.

The exception is **new coverage mislabeled as an absent header**, reported and fixed in Extra E1 below: `test_a_token_that_is_not_an_access_token_is_401[no header type and no claim-<lambda>]` actually constructs header `JWT`; the `typ=None` element in `test_the_legacy_setting_accepts_keycloaks_older_form_and_nothing_weaker` does too. These duplicate another type refusal rather than covering the claimed missing header.

## C7 — REFUTED: no sync-before-serving barrier in the documented CRC order

**Concrete upgrade availability defect:** default mode rejects the old realm's `JWT` / `Bearer` access tokens. Updating the import does not update an existing realm. The new image's sync must run, and clients must then obtain new tokens. **Previously issued tokens remain invalid even after sync**: changing a client attribute cannot rewrite a signed JWT already held by a client. A refresh/new grant after the sync gets the new header (C4).

The runbook does the opposite of the proposed safe order. `head/docs/13-crc-deployment.md:384-385` says:

```bash
oc apply --server-side --field-manager=cmapi-wave1 -R -f "$R/components/cmapi" -f "$R/components/portal"
for d in cmapi-api cmapi-worker cmapi-mockup; do oc rollout status "deploy/$d" -n cmapi --timeout=600s; done
```

Only later, at `:398-402`, it deletes/recreates `cmapi-realm-sync` and waits for completion. The realm Job `head/deploy/manifests/environments/crc/realm/20-realm-sync.yaml:6-29` is a plain batch Job with no ordering annotation or connection to API readiness. Numeric file names are not a Job-completion dependency. The API manifest `head/deploy/manifests/components/cmapi/20-api.yaml:41-69` has only a database migration init container; `:112-125` probes `/readyz`, whose implementation in `head/cmapi/src/cmapi/routers/health.py:33-43` checks the database, not realm convergence. The API can therefore serve unauthenticated health endpoints and return 401 for all otherwise valid old-form bearer tokens before the sync runs. The API's Argo sync-wave annotation does not order this separately applied manual Job.

The compatibility switch **is documented in the identity integration guide** (`head/docs/15-keycloak-integration.md:152-158`, especially `:158`: `auth.acceptLegacyTokenType: true` in `instance.yaml`) and authorization reference (`head/docs/14-authorization.md:141`). The four example instance files add it as a commented opt-in (`head/examples/config/instance.yaml:12`, and matching nonprod/prod/staging files). It is **not mentioned in the CRC runbook**, not in the CRC instance ConfigMap `head/deploy/manifests/environments/crc/20-config.yaml:20-22`, and not exposed by Helm (Extra E2). Thus an identity operator can find the setting in docs/15; an operator following only docs/13 is not warned of this upgrade transition.

Fix: complete the new sync with the old API still running, then renew/age out old access tokens before strict API cutover; alternatively use the documented compatibility setting for the bounded transition. Move the runbook's sync step before workload rollout, retain fail-on-sync-error and policy-before-workload behavior, and explain that cached tokens need renewal. The Job's ServiceAccount/pull secrets are already prepared at `docs/13:199-215`, and its env/volumes need only the earlier Secrets/CA, not the cmapi API. Full replacement steps and the full order regression follow. This tests the executable order written in the runbook; it is not a Kubernetes execution test.

Measured before: `test_realm_sync_completes_before_workload_rollout` fails on `wait_sync < apply_api`. After the replacement: it passes, including the assertion that a failed sync stops the rollout.

Full replacement runbook steps (`report/fixes/rollout_steps.md`):

### Step 20: the realm's mutable parts

Run the new image's sync before rolling the API to strict RFC 9068 token checking. The Job sets access.token.header.type.rfc9068 on callers of cmapi, as well as the user profile, group mappings, read-only LDAP federation and local test users. The service account and Secrets were prepared in earlier steps; the Job needs no API or database connection.

Previously issued tokens keep their original JWT header after the sync. On a live upgrade, keep the old API running while synchronizing, obtain fresh access tokens for clients, and allow the old access-token lifetime plus leeway to elapse before strict cutover. If clients cannot renew in advance, temporarily set instance.yaml auth.acceptLegacyTokenType: true for the transition (docs/15), then remove it after old tokens expire. A refresh after the sync obtains the new header. Do not expect the sync to rewrite cached tokens.

```bash
( set -euo pipefail
  $G gate "$STOP"
  oc delete job cmapi-realm-sync -n cmapi --ignore-not-found
  oc apply --server-side --field-manager=cmapi-wave1 -f "$R/environment/realm/20-realm-sync.yaml"
  rc=0; oc wait job/cmapi-realm-sync -n cmapi --for=condition=Complete --timeout=600s || rc=$?
  oc logs job/cmapi-realm-sync -n cmapi | tee "$RUN/realm-sync.txt"
  [ "$rc" = 0 ]
); stopped $? 20
```

**Stops when** the Job fails. A failed Job is not Complete; read the log. requireSync fails if federation reads nobody, and expectUsers if it reads anything other than the 13 configured test users.

### Step 21: the workloads, the policy first

The policy goes first by itself: the recursive apply would otherwise apply the API before the network policy. Start the strict API only after step 20 has completed successfully and the live-upgrade token transition above is complete.

```bash
( set -euo pipefail
  $G gate "$STOP"
  oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/cmapi/40-networkpolicy.yaml"
  oc apply --server-side --field-manager=cmapi-wave1 -R -f "$R/components/cmapi" -f "$R/components/portal"
  for d in cmapi-api cmapi-worker cmapi-mockup; do oc rollout status "deploy/$d" -n cmapi --timeout=600s; done
); stopped $? 21
```

**Stops when** a rollout is not done.


Full order regression (`report/tests/test_rollout_review184.py`):

```python
"""Hold the documented manual rollout's dependency barrier; no cluster calls."""
import os
from pathlib import Path


def test_realm_sync_completes_before_workload_rollout():
    root = Path(os.environ.get("REVIEW184_HEAD", "head"))
    doc = (root / "docs/13-crc-deployment.md").read_text()
    apply_api = doc.index('oc apply --server-side --field-manager=cmapi-wave1 -R -f "$R/components/cmapi"')
    apply_sync = doc.index('oc apply --server-side --field-manager=cmapi-wave1 -f "$R/environment/realm/20-realm-sync.yaml"')
    wait_sync = doc.index('oc wait job/cmapi-realm-sync -n cmapi --for=condition=Complete')
    assert apply_sync < wait_sync < apply_api, "strict API starts before the realm's access-token header migration"
    barrier = doc[wait_sync:apply_api]
    assert '[ "$rc" = 0 ]' in barrier, "failed sync must stop the rollout"
```



## Extra E1 — REFUTED: the new missing-header test actually has `typ: JWT`

This is a test-coverage defect, not a demonstrated acceptance bug. `head/cmapi/tests/service/conftest.py:70` constructs `headers = {"kid": kid or self.kid, **({"typ": typ} if typ else {})}`. With `typ=None`, the supplied header lacks that key, so PyJWT supplies its own default **JWT**. The fixture's docstring at `:61` acknowledges this. But `head/cmapi/tests/service/test_auth.py:108` labels `k.token("ola", typ=None)` as **“no header type and no claim”**, and `:127` repeats that construction in the legacy rejection loop. Both presently test the `JWT` form again. Those are the two mislabeled/duplicated missing-header cases; other refusal causes are analyzed in C6.

Installed [PyJWT 2.10.1 api_jws.py:137-144](https://github.com/jpadilla/pyjwt/blob/2.10.1/jwt/api_jws.py#L137-L144) first supplies its default header, then applies supplied overrides. In particular: `if not header["typ"]: del header["typ"]`. Explicitly passing `{"typ": None}` removes the type; omitting the override preserves the default.

Before: the regression fails because `jwt.get_unverified_header(keys.token("ola", typ=None))` contains `'typ': 'JWT'`. After: the fixture's None case truly omits `typ`, and the authenticator still rejects it with the expected type error. Passing `typ="JWT"` continues to express the explicit legacy case. The full replacement method belongs inside the existing Keys class (same imports/constants):

```python
def token(self, username: str, *, roles=(), groups=(), employee_id="1001", sub=None, aud=AUDIENCE, iss=ISSUER,
          exp_in=300, client="cmapi-portal", extra: Mapping[str, Any] | None = None, kid=None, alg="RS256",
          typ: str | None = "at+jwt") -> str:
    """`typ` is the JOSE header: an access token of cmapi's realm has at+jwt (RFC 9068). None removes the header type."""
    now = int(time.time())
    claims = {"iss": iss, "aud": [aud, "account"], "sub": sub or f"sub-{username}", "azp": client, "iat": now,
              "exp": now + exp_in, "preferred_username": username, "email": f"{username}@ephico2real.com",
              "given_name": username.title(), "family_name": "Doe", "groups": list(groups),
              "resource_access": {aud: {"roles": list(roles)}}}
    if employee_id:
        claims["employee_id"] = employee_id
    claims.update(extra or {})
    headers = {"kid": kid or self.kid, "typ": typ}
    if alg == "none":
        return jwt.encode(claims, key=None, algorithm="none", headers=headers)
    return jwt.encode(claims, self.pem, algorithm=alg, headers=headers)
```

Full regression:

```python
"""Regression for the test fixture's claimed missing-header case."""
import jwt
from conftest import Keys
from cmapi.core.errors import Problem
from test_auth import make
import pytest


def test_none_really_omits_header_type_and_is_rejected():
    keys = Keys()
    token = keys.token("ola", typ=None)
    assert "typ" not in jwt.get_unverified_header(token)
    with pytest.raises(Problem) as caught:
        make(keys).authenticate(token)
    assert caught.value.status == 401
    assert caught.value.detail == "Token is not an access token"
```


## Extra E2 — REFUTED: the chart does not transmit the documented compatibility setting

`head/cmapi/src/cmapi/core/context.py:78` reads `legacy_token_type=bool(inst["auth"].get("acceptLegacyTokenType", False))`. The new setting is documented in `head/docs/15-keycloak-integration.md:158`, but the chart constructs that instance auth block with only issuer and audience (`head/deploy/helm/cmapi/templates/config.yaml:21-23`). Its values auth block (`head/deploy/helm/cmapi/values.yaml:42-51`) has no compatibility option. The configFiles override loop in `templates/config.yaml:53-61` is restricted to the five policy files and cannot replace `instance.yaml`.

Consequently an operator using an existing older Keycloak cannot enable compatibility through Helm values: `--set auth.acceptLegacyTokenType=true` is silently ignored and the rendered service remains strict. A hand-patched ConfigMap or custom post-renderer could work around that omission, but the chart should render the setting it now needs. The regression renders the real chart with false and true, then parses both YAML layers; false passes before, true fails before. Both pass after the following complete patch to the chart's auth configuration.

```diff
--- a/deploy/helm/cmapi/templates/config.yaml
+++ b/deploy/helm/cmapi/templates/config.yaml
@@ -21,6 +21,7 @@
       auth:
         issuer: {{ .Values.auth.issuer | quote }}
         audience: {{ .Values.auth.audience | quote }}
+        acceptLegacyTokenType: {{ .Values.auth.acceptLegacyTokenType | default false }}
       namespaces:
         reservedPatterns: {{ toJson $inst.reservedPatterns }}
       identity: {{ toJson $inst.identity }}
--- a/deploy/helm/cmapi/values.yaml
+++ b/deploy/helm/cmapi/values.yaml
@@ -40,6 +40,8 @@
 
 # -------------------------------------------------------------------------- identity (an existing Keycloak)
 auth:
+  # Compatibility for an existing Keycloak without at+jwt headers; docs/15.
+  acceptLegacyTokenType: false
   issuer: https://sso.ephico2real.com/realms/ephico2real
   audience: cmapi-nonprod
   # Where the pods fetch the JWKS and call the admin API; default: the issuer. An internal Service
```

Full render regression:

```python
"""The documented compatibility setting must reach the chart's instance.yaml."""
import os
from pathlib import Path
import subprocess

import pytest
import yaml


@pytest.mark.parametrize("enabled", [False, True])
def test_helm_renders_legacy_token_setting(enabled):
    root = Path(os.environ.get("REVIEW184_HEAD", "head"))
    result = subprocess.run(
        ["helm", "template", "cmapi", str(root / "deploy/helm/cmapi"),
         "-f", str(root / "deploy/environments/crc.yaml"),
         "--set", "cmapi.digest=sha256:" + "a" * 64,
         "--set", "trustedCA.certificates=x",
         "--set", f"auth.acceptLegacyTokenType={str(enabled).lower()}"],
        check=True, capture_output=True, text=True,
    )
    config = next(d for d in yaml.safe_load_all(result.stdout)
                  if d and d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "cmapi-config")
    auth = yaml.safe_load(config["data"]["instance.yaml"])["instance"]["auth"]
    assert auth.get("acceptLegacyTokenType", False) is enabled
```


## Verification and limits

All review work and generated files stayed in this folder. `head/` was not edited. No container, Keycloak process, database connection, or cluster command was run. Network reads were the three RFCs and source files/tree metadata from the allowed Keycloak tag. PyJWT evidence came from the installed 2.10.1 source. Live grant issuance, actual Kubernetes scheduling, and the changed historical CI-run statement in `docs/reviews/2026-11-13-issue-181/README.md` were not independently verified. Those unexecuted claims are **PLAUSIBLE**, not counted as new findings. The V1 finding is explicitly conditional on enabling and authorizing that grant; the failing tests there check configuration, not live issuance.

The report includes full tests for every refuted claim and full code/stanzas for each proposed fix. The complete applicable source patch is `report/fixes/review184.patch`; `report/build_fixes.py` materializes it in `report/fixed/head` for verification without touching the export. The small independent signature/type test suite is `report/tests/test_auth_review184.py`.

Commands are run from `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run2/review-184`. Test results are retained in `report/results/`:

```bash
# Original reviewed authentication tests: 44 passed (22 + 22).
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=head/cmapi/src:head/cmapi/tests/service \
  /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest \
  -p no:cacheprovider head/cmapi/tests/service/test_auth.py \
  head/cmapi/tests/service/test_review_b_auth.py

# Full independent review suite on the original: 6 failed, 30 passed.
# The failures are: optional scope, absent-header fixture, CRC order,
# V1 target configuration (CRC and Helm), and Helm compatibility=true.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=head/cmapi/src:head/cmapi/tests/service \
  /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest \
  -p no:cacheprovider report/tests

python3 report/build_fixes.py

# Same review tests with proposed fixes: 36 passed.
PYTHONDONTWRITEBYTECODE=1 REVIEW184_HEAD=report/fixed/head \
  PYTHONPATH=report/fixed/head/cmapi/src:report/fixed/head/cmapi/tests/service \
  /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest \
  -p no:cacheprovider report/tests

# Existing selected database-free checks with proposals: 94 passed.
PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=report/fixed/head/cmapi/src:report/fixed/head/cmapi/tests/service \
  /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest \
  -p no:cacheprovider \
  report/fixed/head/cmapi/tests/service/test_auth.py \
  report/fixed/head/cmapi/tests/service/test_review_b_auth.py \
  report/fixed/head/cmapi/tests/service/test_plain_manifests.py \
  report/fixed/head/cmapi/tests/service/test_review_h_tools_migrate.py::test_realm_sync_runs_and_prints_no_secret
```

The only emitted warning in these runs is Starlette's existing AnyIO deprecation warning.
