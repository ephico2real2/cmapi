"""The exact GET /api/v1/metadata-keys body that design.md specifies, for both configs.

main's generator (MetadataKeys.json_schema, #328) with the two additions of design.md, D5: `title` (from the new optional
rule field) and `x-cmapi-rule` (rule.text), in the key order of the proposed _rule_schema; the reference config with the
proposed titles and the mockup's words as descriptions (D6). The additions are applied here to main's output, so this
script needs no change to cmapi. Run: PYTHONPATH=<export>/cmapi/src python designed_response.py <export>"""
import json, sys
from pathlib import Path
import yaml
import cmapi.core.metadata as m

root = Path(sys.argv[1])
here = Path(__file__).parent
TITLES = {"reference": {("label", "cmapi.net/team"): "Team", ("annotation", "cmapi.net/team-dl"): "Team DL"}, "company": {}}
DESCRIPTIONS = {"reference": {
    ("label", "cmapi.net/team"): "Who owns it, for cost and notices: any team name. Not checked against who you are; your Keycloak roles decide what you may do",
    ("annotation", "cmapi.net/team-dl"): "Your team's distribution list, in one of the organisation's email domains (emailDomains); format only"}, "company": {}}
STANZA = {"label": "requiredLabels", "annotation": "requiredAnnotations"}


def designed(name, rel):
    raw = yaml.safe_load((root / rel).read_text())
    for (kind, key), text in DESCRIPTIONS[name].items():
        raw[STANZA[kind]][key]["description"] = text
    keys = m.MetadataKeys(raw)
    body = {}
    for kind, field in (("label", "labels"), ("annotation", "annotations")):
        schema = keys.json_schema(kind, "create")
        for key, rule in keys.rules[kind].items():
            prop, out = schema["properties"][key], {}
            for k, v in prop.items():
                if k == "description":
                    if (kind, key) in TITLES[name]:
                        out["title"] = TITLES[name][(kind, key)]
                    out["description"] = v
                    out["x-cmapi-rule"] = rule.text(keys.email_domains)
                else:
                    out[k] = v
            schema["properties"][key] = out
        body[field] = schema
    return body


for name, rel in (("reference", "examples/cluster-configs/policies/metadata-keys.yaml"),
                  ("company", "examples/cluster-configs/policies/metadata-keys.company.yaml")):
    body = designed(name, rel)
    (here / f"designed-response-{name}.json").write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n")
    print(name, len(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()), "bytes compact")
