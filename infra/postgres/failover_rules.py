"""Decisions of the node supervisor (pure: no database, no processes). Unit-tested in
tests/unit/test_failover_rules.py; executed by supervisor.py every tick, per cluster.

Each database (cluster) lives in two places of the ring: its HOME node and the node that
keeps its COPY (a streaming standby). One of them is the primary, the other follows it.

    home primary, copy standby      normal operation (synchronous replication)
    home fails                      the copy is promoted and takes over its role
    home comes back                 it re-syncs from the copy, then takes its role back
                                    (switchover: copy hands over and becomes the copy again)

Never two primaries accepting writes: a primary that cannot reach its peer NOR any other
node (witness) assumes it is the isolated one and fences itself (read-only); a standby only
takes over if it can still reach a witness. If two primaries meet, the one on the newest
timeline (the one promoted last) wins and the other steps down.
"""
from dataclasses import dataclass


@dataclass
class Status:
    """What a running cluster reports."""
    primary: bool
    timeline: int = 0             # current timeline (primaries only)
    read_only: bool = False       # fenced
    sync: bool = False            # synchronous replication on (primaries only)
    peer_streaming: bool = False  # (primary) the peer streams from it
    peer_caught_up: bool = False  # (primary) ... with no replay lag
    streaming: bool = False       # (standby) receiving WAL from the primary


RESYNC_AFTER = 30   # seconds a standby may fail to stream from a live primary before re-syncing

# Actions
INIT_PRIMARY = "INIT_PRIMARY"   # empty data dir, nobody to copy from: initdb + init scripts
CLONE = "CLONE"                 # empty data dir: base backup from the peer, start as standby
WAIT = "WAIT"                   # nothing to do yet (e.g. copy waiting for its home)
START = "START"                 # existing data dir: start as it was
STEP_DOWN = "STEP_DOWN"         # re-sync from the peer (base backup) and run as its standby
PROMOTE = "PROMOTE"             # standby -> primary (takes over the role)
SWITCHOVER = "SWITCHOVER"       # promoted copy hands the role back to the home
FENCE = "FENCE"                 # read-only (isolated primary)
UNFENCE = "UNFENCE"
SYNC_ON = "SYNC_ON"             # synchronous replication to the peer
SYNC_OFF = "SYNC_OFF"           # peer is down: keep accepting writes alone
OK = "OK"


def decide(*, role: str, has_data: bool, standby_signal: bool, local: Status | None,
           peer: Status | None, witness_ok: bool, peer_missing_for: float,
           streamed_before_loss: bool, failover_after: float, not_streaming_for: float = 0) -> str:
    """One decision for one cluster.

    role               "home" or "copy"
    has_data           the data directory is initialised
    standby_signal     the data directory is configured as a standby
    local              status of the local cluster (None: not running)
    peer               status of the other location (None: unreachable)
    witness_ok         at least one other node of the system answers
    peer_missing_for   seconds since the peer stopped being a primary (0 if it is one)
    streamed_before_loss  (copy) was receiving WAL right before the home disappeared
    """
    # ---- not running ----
    if local is None:
        if not has_data:
            if peer is not None and peer.primary:
                return CLONE
            return INIT_PRIMARY if role == "home" else WAIT
        if not standby_signal and peer is not None and peer.primary:
            return STEP_DOWN          # it took over while we were away: never a 2nd primary
        return START

    # ---- running as primary ----
    if local.primary:
        if peer is not None and peer.primary:
            if local.timeline != peer.timeline:
                return STEP_DOWN if local.timeline < peer.timeline else OK
            return STEP_DOWN if role == "copy" else OK
        # pg_stat_replication may still say "streaming" for a peer cut off by the network
        # (until wal_sender_timeout): only trust it if we can actually reach the peer.
        streaming = local.peer_streaming and peer is not None
        if role == "copy" and streaming and local.peer_caught_up:
            return SWITCHOVER         # the home is back and in step: give its role back
        if streaming:
            if not local.sync:
                return SYNC_ON
            return UNFENCE if local.read_only else OK
        if not witness_ok:
            return FENCE if not local.read_only else OK      # isolated: stop accepting writes
        if local.sync:
            return SYNC_OFF                                    # peer is down, we are not
        return UNFENCE if local.read_only else OK

    # ---- running as standby ----
    if peer is not None and peer.primary:
        # Following the primary. If it cannot stream from it for long (e.g. its history
        # diverged), throw the local copy away and take a fresh one.
        return STEP_DOWN if not_streaming_for > RESYNC_AFTER else OK
    if role == "home" and peer is not None:
        return PROMOTE                # both standby: the copy handed the role back
    if peer_missing_for < failover_after:
        return WAIT
    if role == "home":
        # The copy is gone and we still see the rest of the system: the home takes its role.
        return PROMOTE if witness_ok else WAIT
    # The copy only takes over a home that is really gone, if it was in step with it and
    # if it is not itself the isolated one.
    if peer is None and witness_ok and streamed_before_loss:
        return PROMOTE
    return WAIT
