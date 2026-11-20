import copy
import json

from test_api_samples import SAMPLES, compare


def test_sample_comparison_catches_a_wrong_source_even_if_the_json_shape_is_unchanged():
    committed = json.loads(SAMPLES.read_text())
    changed = copy.deepcopy(committed)
    sample = changed["operations"]["namespaces_create_namespace:dryRun"]
    team = sample["response"]["body"]["metadata"]["labels"]["cmapi.net/team"]
    team["source"] = "namespace"
    assert compare(committed, changed)
