import json
from types import SimpleNamespace

from starlette.requests import Request
from cmapi.core.metadata import MetadataKeys
from cmapi.plugins.expiration.rules import ExpirationRules
from cmapi.routers.me import metadata_keys


def test_expiration_only_config_change_invalidates_the_form_contract_etag():
    cfg = SimpleNamespace(metadata=MetadataKeys({}), raw_instance={"instance": {"allowedEnvironments": ["dev"]}})
    ctx = SimpleNamespace(cfg=cfg)
    def read(enabled, previous=None):
        cfg.expiration = ExpirationRules({"environments": {"dev": {"enabled": enabled}}})
        headers = [(b"if-none-match", previous.encode())] if previous else []
        return metadata_keys(Request({"type": "http", "headers": headers}), who=None, c=ctx)
    first = read(True)
    second = read(False, first.headers["etag"])
    assert second.status_code == 200
    assert second.headers["etag"] != first.headers["etag"]
    assert json.loads(second.body)["x-cmapi-expiration"]["environments"]["dev"] == {"enabled": False}
