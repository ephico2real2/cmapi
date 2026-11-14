"""The Fable review of #234 (#215), through the API: the example of labels and annotations comes from the file."""
from __future__ import annotations

from conftest import EXAMPLES  # noqa: F401  (the fixtures of test_metadata_stanzas_api need the same conftest)
from test_flow import OLA, auth
from test_metadata_stanzas_api import URL, body, company  # noqa: F401


def test_the_api_documents_example_is_one_that_this_instance_accepts(company):
    client, ctx, git, kube, validator, keys = company
    props = client.get("/openapi.json").json()["components"]["schemas"]["NamespaceCreate"]["properties"]
    # c830276: [{"cmapi.net/team": "payments"}], the model's fixed example, which this instance refuses.
    assert props["labels"]["examples"] == [{"company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1"}]
    assert props["annotations"]["examples"] == [{}]
    r = client.post(URL + "?dryRun=true", headers=auth(keys, "ola", **OLA),
                    json=body(labels=props["labels"]["examples"][0], annotations=props["annotations"]["examples"][0]))
    assert r.status_code == 200, r.text


def test_a_number_for_a_label_value_is_a_validation_problem_not_an_error(company):
    """Evidence for the review's edge case (cl: 1 against '1'); passes before and after."""
    client, ctx, git, kube, validator, keys = company
    labels = {"company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": 1}
    r = client.post(URL + "?dryRun=true", json=body(labels=labels), headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422 and r.json()["code"] == "validation-failed", r.text
