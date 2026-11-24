"""Takeover rules of the node supervisor (infra/postgres/failover_rules.py)."""
import json
from pathlib import Path

import failover_rules as R
from failover_rules import Status

PRIMARY = Status(primary=True, timeline=1)
STANDBY = Status(primary=False, streaming=True)


def decide(**kw):
    base = dict(role="copy", has_data=True, standby_signal=True, local=STANDBY, peer=PRIMARY,
                witness_ok=True, peer_missing_for=0, streamed_before_loss=True, failover_after=6)
    return R.decide(**{**base, **kw})


# ---------- first start ----------

def test_home_without_data_and_nobody_to_copy_initialises():
    assert decide(role="home", has_data=False, local=None, peer=None) == R.INIT_PRIMARY


def test_copy_without_data_waits_for_its_home_then_clones_it():
    assert decide(has_data=False, local=None, peer=None) == R.WAIT
    assert decide(has_data=False, local=None, peer=PRIMARY) == R.CLONE


def test_home_that_lost_its_data_copies_back_from_the_copy_that_took_over():
    assert decide(role="home", has_data=False, local=None, peer=PRIMARY) == R.CLONE


# ---------- the home fails: the copy takes over ----------

def test_copy_keeps_following_a_live_home():
    assert decide() == R.OK


def test_copy_waits_a_few_seconds_before_taking_over():
    assert decide(peer=None, peer_missing_for=3) == R.WAIT
    assert decide(peer=None, peer_missing_for=7) == R.PROMOTE


def test_isolated_copy_never_takes_over():
    assert decide(peer=None, peer_missing_for=60, witness_ok=False) == R.WAIT


def test_copy_that_was_not_in_step_with_the_home_never_takes_over():
    assert decide(peer=None, peer_missing_for=60, streamed_before_loss=False) == R.WAIT


def test_copy_that_cannot_stream_from_a_live_primary_resyncs():
    assert decide(local=Status(primary=False), not_streaming_for=40) == R.STEP_DOWN


# ---------- the home comes back ----------

def test_home_that_was_primary_comes_back_as_copy_of_who_took_over():
    assert decide(role="home", standby_signal=False, local=None, peer=PRIMARY) == R.STEP_DOWN


def test_home_restarted_quickly_is_still_the_primary():
    assert decide(role="home", standby_signal=False, local=None, peer=STANDBY) == R.START


def test_promoted_copy_hands_the_role_back_once_the_home_is_in_step():
    promoted = Status(primary=True, timeline=2, peer_streaming=True, peer_caught_up=False, sync=True)
    assert decide(local=promoted, peer=STANDBY) == R.OK
    assert decide(local=Status(primary=True, timeline=2, peer_streaming=True, peer_caught_up=True),
                  peer=STANDBY) == R.SWITCHOVER


def test_home_takes_its_role_back_when_both_are_standby():
    assert decide(role="home", local=Status(primary=False), peer=Status(primary=False)) == R.PROMOTE


# ---------- never two primaries ----------

def test_of_two_primaries_the_older_timeline_steps_down():
    assert decide(role="home", local=Status(primary=True, timeline=1), peer=Status(primary=True, timeline=2)) == R.STEP_DOWN
    assert decide(local=Status(primary=True, timeline=2), peer=Status(primary=True, timeline=1)) == R.OK


def test_same_timeline_the_home_wins():
    assert decide(role="home", local=PRIMARY, peer=PRIMARY) == R.OK
    assert decide(role="copy", local=PRIMARY, peer=PRIMARY) == R.STEP_DOWN


def test_isolated_primary_fences_itself():
    assert decide(role="home", local=Status(primary=True, timeline=1, sync=True), peer=None,
                  witness_ok=False) == R.FENCE


# ---------- synchronous replication ----------

def test_sync_on_while_the_copy_streams_and_off_when_it_is_down():
    assert decide(role="home", local=Status(primary=True, peer_streaming=True), peer=STANDBY) == R.SYNC_ON
    assert decide(role="home", local=Status(primary=True, sync=True), peer=None) == R.SYNC_OFF


def test_copy_cut_off_by_the_network_is_not_trusted_as_streaming():
    """After a partition pg_stat_replication still shows the old walsender as streaming:
    if the copy cannot be reached, stop waiting for it (or every commit would hang)."""
    stale = Status(primary=True, sync=True, peer_streaming=True, peer_caught_up=True)
    assert decide(role="home", local=stale, peer=None) == R.SYNC_OFF
    assert decide(role="home", local=stale, peer=None, witness_ok=False) == R.FENCE
    assert decide(role="copy", local=Status(primary=True, timeline=2, peer_streaming=True, peer_caught_up=True),
                  peer=None) != R.SWITCHOVER


def test_fenced_primary_resumes_when_it_sees_the_system_again():
    assert decide(role="home", local=Status(primary=True, read_only=True), peer=None) == R.UNFENCE


# ---------- topology ----------

def test_ring_every_cluster_has_its_copy_on_another_node_and_no_port_clash():
    topo = json.loads((Path(__file__).resolve().parents[2] / "common" / "topology.json").read_text())
    used = set()
    for name, spec in topo["clusters"].items():
        assert spec["home"][0] != spec["copy"][0], name
        for host, port in (spec["home"], spec["copy"]):
            assert (host, port) not in used
            used.add((host, port))
    # ring of the shards: EU -> AM node, AM -> AF node, AF -> EU node
    assert [topo["clusters"][r]["copy"][0] for r in ("EU", "AM", "AF")] == ["pg-america", "pg-africa", "pg-europa"]
