"""Three readers that took a value for something it is not, found by the second pass of PR #579.

#583, If-None-Match (core/etag.py, etag_matches). RFC 9110 section 13.1.2 (https://www.rfc-editor.org/rfc/rfc9110.txt, read
2026-11-23): `If-None-Match = "*" / #entity-tag`, by the weak comparison (section 8.8.3.2: "two entity tags are equivalent if
their opaque-tags match character-by-character, regardless of either or both being tagged as \"weak\""). An opaque tag may
hold a comma or a `*` (section 8.8.3, etagc), so splitting on "," read one tag as several and `"previous,*,draft"` as `*`.
A value that is not such a list matches nothing (13.1.2, step 3: "Otherwise, the condition is true"). Several field lines are
one list (section 5.3).

#584, the namespace ETag (core/pipeline.py, folder_etag). A strong validator "changes value whenever a change occurs to the
representation data" (section 8.8.1). plan_hash writes an empty file as `<deleted>`, so a file emptied in Git, or one that
holds a NUL, could keep the folder's tag.

#585, caData (core/registry.py, _valid_ca_data). RFC 7468 section 2 (https://www.rfc-editor.org/rfc/rfc7468.txt, read
2026-11-23): textual encoding "begins with a line comprising \"-----BEGIN \", a label, and \"-----\", and ends with a line
comprising \"-----END \", a label, and \"-----\"", and "Data before the encapsulation boundaries are permitted". A block with
no END line was read as bare base64, and the regex rescanned the rest of the value from every BEGIN line.

The functions are imported inside each test, so that this file also runs on main and shows each failure there.
"""
from __future__ import annotations

import time

import pytest

# ---------------------------------------------------------------- #583 If-None-Match


@pytest.mark.parametrize("value, etag, matches", [
    ('"previous,*,draft"', '"abc"', False),      # one tag holding ",*,": not *
    ('"x,abc"', '"abc"', False),                 # one tag holding a comma: not split on ","
    ('W/"a,b"', '"a,b"', True),                  # weak comparison, on a tag that holds a comma
    ("*", '"abc"', True),
    (" \t*\t ", '"abc"', True),                  # OWS around * (section 5.6.3)
    ('"abc"', '"abc"', True),
    ('W/"abc"', '"abc"', True),
    ('"other", W/"abc"', '"abc"', True),
    ('"other",, "abc" ,', '"abc"', True),        # empty list elements are skipped (section 5.6.1.2)
    ('"other"', '"abc"', False),
    ('"abc", junk', '"abc"', False),             # not a list of entity tags: nothing matches
    ('"abc", *', '"abc"', False),                # * is the whole value or nothing
    ('"abc" "x"', '"abc"', False),               # two tags with no comma
    ("abc", '"abc"', False),                     # no quotes: If-Match's recovery is for the writes only
    ("", '"abc"', False),
    (None, '"abc"', False),
    ("\xa0*\xa0", '"abc"', False),               # NBSP is not HTTP whitespace (section 5.6.3)
])
def test_if_none_match_reads_rfc_9110s_list(value, etag, matches):
    from cmapi.core.etag import etag_matches
    assert etag_matches(value, etag) is matches


def test_if_match_keeps_its_reading():
    """if_match_tags now shares the list parser: what it lists is unchanged (test_if_match_forms_571.py has the full table)."""
    from cmapi.core.etag import if_match_tags
    assert if_match_tags('"a,b" , W/"c", "d"') == ["a,b", "d"]
    assert if_match_tags("a") == ["a"] and if_match_tags('"a", junk') == [] and if_match_tags("*") == []


def test_a_document_answers_304_to_a_list_on_two_lines(world):
    """The real route (main.py, /openapi.json): the field lines are joined before the comparison (section 5.3)."""
    client, *_ = world
    etag = client.get("/openapi.json").headers["etag"]
    two_lines = client.get("/openapi.json", headers=[("If-None-Match", '"older"'), ("If-None-Match", etag)])
    assert two_lines.status_code == 304 and two_lines.content == b"" and two_lines.headers["etag"] == etag


def test_a_document_answers_200_to_a_tag_holding_star(world):
    """The real route: a tag that holds ",*," is one tag, not the document's, so the body is sent."""
    client, *_ = world
    etag = client.get("/openapi.json").headers["etag"]
    starred = client.get("/openapi.json", headers={"If-None-Match": '"previous,*,draft"'})
    assert starred.status_code == 200 and starred.headers["etag"] == etag


# ---------------------------------------------------------------- #584 the namespace ETag

NS = {"namespace.yaml": "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: payments-dev\n"}


def test_absent_empty_and_the_marker_give_three_tags():
    from cmapi.core.pipeline import folder_etag
    tags = {folder_etag(NS), folder_etag({**NS, "extra.yaml": ""}), folder_etag({**NS, "extra.yaml": "<deleted>"})}
    assert len(tags) == 3
    assert folder_etag({}) == "0"


def test_a_nul_in_a_file_is_not_a_file_boundary():
    """plan_hash ends each path and each content with NUL, so one file holding "x NUL b.yaml NUL y" read as two files."""
    from cmapi.core.pipeline import folder_etag
    assert folder_etag({"a.yaml": "x\0b.yaml\0y"}) != folder_etag({"a.yaml": "x", "b.yaml": "y"})


@pytest.mark.parametrize("files, tag", [
    (NS, "809899d2a47c256a"),
    ({**NS, "extra.yaml": ""}, "593d77cc82483bd9"),
    ({**NS, "quota.yaml": "kind: ResourceQuota\n"}, "2b1ce36603f09c96"),
])
def test_every_other_folder_keeps_its_tag(files, tag):
    """The tags folder_etag gave on main (9876fee), measured there: a tag a client holds does not go stale on upgrade."""
    from cmapi.core.pipeline import folder_etag
    assert folder_etag(files) == tag


# ---------------------------------------------------------------- #585 caData

BEGIN = "-----BEGIN CERTIFICATE-----\n"
END = "-----END CERTIFICATE-----\n"


@pytest.mark.parametrize("ca_data, valid", [
    (BEGIN + "YQ==\n", False),                                     # a block with no END line
    (BEGIN + "YQ==\n" + END + BEGIN + "YWI=\n", False),            # a complete block, then one with no END line
    ("YQ==\n" + END, False),                                       # an END line with no BEGIN line
    ("YQ==", True),                                                # bare base64, as before
    (BEGIN + "YQ==\n" + END + BEGIN + "YWI=\n" + END, True),       # a bundle, each block padded by itself
    ("# CA one\n" + BEGIN + "YQ==\n" + END + "\n# CA two\n" + BEGIN + "YWI=\n" + END, True),  # text around (RFC 7468)
    ((BEGIN + "YQ==\n" + END).replace("\n", "\r\n"), True),        # CRLF lines
    (BEGIN + "Y Q = =\n" + END, True),                             # whitespace inside the body is ignored, as before
    (BEGIN + "YQ=\n" + END, False),                                # not base64
    (BEGIN + END, False),                                          # an empty block
])
def test_ca_data_needs_complete_blocks(ca_data, valid):
    from cmapi.core.registry import _valid_ca_data
    assert _valid_ca_data(ca_data) is valid


def test_a_large_malformed_bundle_is_read_in_linear_time():
    """#585: 2,000 BEGIN lines and no END line, 186 kB, inside a Secret's 1 MiB (https://kubernetes.io/docs/concepts/
    configuration/secret/, "Individual Secrets are limited to 1MiB in size", read 2026-11-23). The regex took 4.4 s of CPU
    on main, under the registry's refresh lock; the boundary scan takes about 1 ms. CPU time of this process, not wall time,
    so a busy runner does not inflate it; the bound leaves the linear scan a margin of over 100 times and is under a tenth
    of the quadratic one."""
    from cmapi.core.registry import _valid_ca_data
    ca_data = (BEGIN + "QUFB" * 16 + "\n") * 2000
    start = time.process_time()
    valid = _valid_ca_data(ca_data)
    assert time.process_time() - start < 0.25, "the caData check is no longer linear in the length of the value"
    assert not valid, "no block is closed"
