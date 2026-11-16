"""#184 (SEC-07), Codex's review, C5: the sync types each client that can get a token for cmapi. No server: a paged stub of the admin API."""
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
