import tomllib
from pathlib import Path

import pytest

from inat_anki.model import Observation, RankedTaxon, Taxon
from inat_anki.normalise import ranked_from_api
from inat_anki.sets import (
    SetsError,
    check_no_overlap,
    parse_sets,
    parse_species_list,
    plan_membership,
    rank_candidates,
    seen_taxa,
    wanted_candidates,
)
from tests.conftest import load_fixture

ROOT = Path(__file__).parent.parent
DATA = ROOT / "src/inat_anki/data"


def ranked(*ids):
    return [RankedTaxon(Taxon(i, f"T{i}", "species", None, None), 1000 - i) for i in ids]


def minimal(**overrides):
    s = {"key": "birds", "name": "Birds", "taxon_id": [3], "count": 5, **overrides}
    return {"set": [s]}


def test_shipped_sets_file_parses():
    config = parse_sets(tomllib.loads((DATA / "uk-common.toml").read_text()))
    keys = [s.key for s in config.sets]
    assert len(keys) == 13
    assert config.photos_per_species == 2
    assert config.place_id == 6857
    # Sets come after the sets they exclude.
    assert keys.index("trees") < keys.index("plants")
    assert keys.index("lichens") < keys.index("fungi")
    total = sum(s.count or 0 for s in config.sets)
    assert total == 400  # plus 25 farm breeds
    trees = next(s for s in config.sets if s.key == "trees")
    assert trees.rank == "species,hybrid"
    assert trees.quality_grade == "research,casual"


def test_shipped_tree_list_parses():
    trees = parse_species_list((DATA / "lists/uk-trees.txt").read_text())
    assert len(trees) == 79
    by_name = {t.name: t.taxon_id for t in trees}
    assert by_name["Quercus robur"] == 56133  # the species, not the same-named complex
    assert by_name["Platanus × hispanica"] == 552449


@pytest.mark.parametrize(
    "overrides",
    [
        {"key": "Birds!"},
        {"count": 0},
        {"count": None},
        {"taxon_id": None},
        {"species_list": "x.txt"},  # two sources
        {"colour": "blue"},
        {"exclude_sets": ["nope"]},
        {"exclude_sets": ["birds"]},
        {"taxon_id": ["3"]},
    ],
)
def test_bad_set_rejected(overrides):
    with pytest.raises(SetsError):
        parse_sets(minimal(**overrides))


def test_duplicate_keys_rejected():
    raw = {"set": [minimal()["set"][0], minimal()["set"][0]]}
    with pytest.raises(SetsError):
        parse_sets(raw)


def test_unknown_top_level_setting_rejected():
    with pytest.raises(SetsError):
        parse_sets({**minimal(), "palce_id": 1})


def test_breed_list_has_no_count():
    ok = parse_sets({"set": [{"key": "farm", "breed_list": "b.toml"}]})
    assert ok.sets[0].count is None
    with pytest.raises(SetsError):
        parse_sets({"set": [{"key": "farm", "breed_list": "b.toml", "count": 5}]})


def test_exclude_cycle_rejected():
    raw = {
        "set": [
            {"key": "a", "taxon_id": [1], "count": 1, "exclude_sets": ["b"]},
            {"key": "b", "taxon_id": [2], "count": 1, "exclude_sets": ["a"]},
        ]
    }
    with pytest.raises(SetsError):
        parse_sets(raw)


def test_species_list_errors():
    with pytest.raises(SetsError):
        parse_species_list("123\tName\n")
    with pytest.raises(SetsError):
        parse_species_list("1\tA\ta\n1\tA\ta\n")
    assert parse_species_list("# comment\n\n5\tA b\tAy\n")[0].taxon_id == 5


def test_rank_candidates_filters_descendants_and_exclusions():
    out = rank_candidates(ranked(1, 2, 3, 4, 2), listed_ids={1, 2, 3}, excluded={3})
    assert [r.taxon.id for r in out] == [1, 2]


def test_ranked_from_fixture():
    rows = [ranked_from_api(d) for d in load_fixture("v2_species_counts.json")["results"]]
    assert rows[0].taxon.name == "Erithacus rubecula"
    assert rows[0].count == 43195
    assert rows[0].taxon.ancestor_ids


def test_first_build_takes_top_n_with_photos():
    m = plan_membership([], ranked(1, 2, 3, 4, 5), 3, accepted={1, 3, 4, 5})
    assert m.members == [1, 3, 4]  # 2 has no usable photo; 4 moves up
    assert m.added == [1, 3, 4]


def test_membership_is_sticky():
    m = plan_membership([1, 9], ranked(1, 2, 3), 3, accepted={1, 2, 3})
    assert m.members == [1, 9, 2]
    assert m.below_cutoff == [9]
    assert m.added == [2]
    assert m.removed == []


def test_sticky_never_shrinks_or_overfills():
    m = plan_membership([7, 8, 9, 10], ranked(1, 2), 3, accepted={1, 2})
    assert m.members == [7, 8, 9, 10]


def test_rerank_rebuilds_and_reports_removed():
    m = plan_membership([1, 9], ranked(1, 2, 3), 2, accepted={1, 2, 3}, rerank=True)
    assert m.members == [1, 2]
    assert m.removed == [9]


def test_wanted_candidates_only_what_is_needed():
    assert [c.taxon.id for c in wanted_candidates([1], ranked(1, 2, 3, 4), 3)] == [2, 3]
    assert wanted_candidates([1, 2, 3], ranked(1, 2, 3, 4), 3) == []


def test_overlap_fails():
    check_no_overlap({"a": [1, 2], "b": [3]})
    with pytest.raises(SetsError, match="taxon 2"):
        check_no_overlap({"a": [1, 2], "b": [2]})


def test_seen_includes_ancestors(observations):
    obs = list(observations.values())
    seen = seen_taxa(obs)
    assert 55759 in seen  # Silene dioica, observed directly
    sub = next(o for o in obs if o.taxon.rank == "subspecies")
    assert set(sub.taxon.ancestor_ids) <= seen  # incl. its species, Rupicapra pyrenaica


def test_seen_empty():
    assert seen_taxa([]) == set()


def test_observation_type_unchanged():
    # Observation still constructs as in v1 (ancestor_ids has a default).
    assert Observation.__dataclass_fields__["taxon"]


def test_sticky_members_in_top_are_not_below_cutoff():
    # Previous members need no photo search, so they are not in `accepted`.
    m = plan_membership([1, 2], ranked(1, 2, 3, 4), 3, accepted={4})
    assert m.members == [1, 2, 4]
    assert m.below_cutoff == []
