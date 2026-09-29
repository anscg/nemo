import pathlib

import pytest

from ingest import member_links as links

WHOLE = 1000


def rarity(crowd, whole=WHOLE):
    import math
    if whole <= 2 or crowd <= 1:
        return 1.0
    if crowd >= whole:
        return 0.0
    return min(1.0, max(0.0, math.log(whole / crowd) / math.log(whole / 2)))


def score_for(name, crowd, whole=WHOLE):
    return links.signals()[name]["weight"] * rarity(crowd, whole)


def test_every_signal_carries_a_weight_a_label_and_a_ceiling():
    for name, one in links.signals().items():
        assert one["weight"] > 0, name
        assert one["label"], name
        assert one["crowd_ceiling"] >= 2, name


def test_the_bands_climb():
    marks = links.scoring()
    assert marks["floor"] < marks["strong"] < marks["certain"]


def test_a_value_only_two_people_share_scores_the_whole_weight():
    assert score_for("ip_exact", 2) == pytest.approx(5.0)
    assert score_for("ip_prefix", 2) == pytest.approx(3.0)


def test_a_value_a_crowd_shares_is_worth_almost_nothing():
    assert score_for("ip_prefix", 20) < 2.1
    assert score_for("email_domain", 30) < 1.4


def test_a_school_domain_cannot_link_two_people_on_its_own():
    marks = links.scoring()
    assert score_for("email_domain", 6) < marks["floor"], \
        "six people on one domain is a school, not an alt"
    assert score_for("joined_together", 2) < marks["floor"], \
        "arriving together is a crowd signal, not an identity"


def test_two_weak_signals_together_do_reach_the_floor():
    marks = links.scoring()
    together = score_for("email_domain", 6) + score_for("joined_together", 2)
    assert together >= marks["floor"]


def test_one_address_two_people_is_the_strongest_thing_we_have():
    marks = links.scoring()
    assert score_for("ip_exact", 2) >= marks["strong"]


def test_the_agent_only_corroborates_so_a_shared_browser_links_nobody():
    assert links.corroborating() == ["session_agent"]
    assert "session_agent" not in [
        name for name, one in links.signals().items() if not one.get("corroborating")
    ]


def test_the_landing_refuses_a_pair_held_up_by_corroboration_alone():
    assert "NOT (signal = ANY (%(corroborating)s))" in links.LAND
    assert "> 0" in links.LAND


def test_a_pair_is_written_one_way_round_so_it_cannot_be_held_twice():
    said = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
            / "0149_member_links.sql").read_text()
    assert "CHECK (a_user_id < b_user_id)" in said
    assert "PRIMARY KEY (a_user_id, b_user_id)" in said
    assert "least(a.user_id, b.user_id)" in links.PAIRS_SQL


def test_a_link_nothing_supports_any_more_is_swept_rather_than_left_standing():
    assert links.SWEEP.startswith("DELETE FROM fd.member_link")
    assert "computed_at <" in links.SWEEP


def test_the_crowd_ceiling_keeps_a_cgnat_out_of_the_join_entirely():
    assert "c.people BETWEEN 2 AND %(ceiling)s" in links.PAIRS_SQL


def test_every_signal_the_catalogue_names_can_actually_be_gathered():
    known = set(links.EVIDENCE) | {links.JOINED_TOGETHER}
    assert set(links.signals()) <= known
