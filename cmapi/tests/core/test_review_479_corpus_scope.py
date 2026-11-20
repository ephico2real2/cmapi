from cmapi.core.metadata import MetadataKeys
import metadata_corpus as corpus


def test_a_required_patch_regression_is_not_excused_as_an_omitted_create_value(monkeypatch):
    keys = MetadataKeys({"requiredLabels": {"name": {"value": {"from": "namespace"}}}})
    schemas = {(kind, op): keys.json_schema(kind, op) for kind in ("label", "annotation") for op in ("create", "patch")}
    schemas["label", "patch"]["required"] = ["name"]
    case = corpus.Case("label", "patch", {})
    monkeypatch.setattr(corpus, "cases", lambda keys: [case])
    result = corpus.run(keys, schemas, {"namespace": "a-good-name"})
    assert [c for c, _ in result.unsound] == [case]
    assert result.filled == 0


def test_the_corpus_recognizes_a_target_dependent_suffix_refusal(monkeypatch):
    keys = MetadataKeys({"requiredLabels": {"env": {"value": {"from": "environment"}, "namespaceSuffix": True}}})
    schemas = {(kind, op): keys.json_schema(kind, op) for kind in ("label", "annotation") for op in ("create", "patch")}
    monkeypatch.setattr(corpus, "cases", lambda keys: [corpus.Case("label", "create", {"env": "dev"})])
    result = corpus.run(keys, schemas, {"namespace": "a-good-name-qa", "environment": "dev"})
    assert result.unexplained == []
    assert result.loose == {"namespaceSuffix": 1}
