"""Pure-Python tests for WatermarkAdversary's use of true send-sequence
numbers instead of arrival-list index, which is what keeps detection
correct once a packet is lost downstream of the watermark relay."""
import random

from anontestlab.adversary.base import SessionObservation, SimulationContext
from anontestlab.adversary.watermark import WatermarkAdversary


def _ctx(obs: SessionObservation) -> SimulationContext:
    return SimulationContext(sessions={0: obs}, session_paths={0: [["n0", "n1", "n2"]]}, node_ids=["n0", "n1", "n2"])


def _old_index_based_rate(times: list[float], period: int, delay_s: float, detection_fraction: float) -> float:
    """The pre-fix logic, kept here only to demonstrate what it would
    have concluded on the same data: classifies gaps by arrival index."""
    times = sorted(times)
    gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    watermark_gaps = [g for i, g in enumerate(gaps) if (i + 2) % period == 0]
    other_gaps = [g for i, g in enumerate(gaps) if (i + 2) % period != 0]
    mean_watermark = sum(watermark_gaps) / len(watermark_gaps)
    mean_other = sum(other_gaps) / len(other_gaps)
    return 1.0 if mean_watermark - mean_other > delay_s * detection_fraction else 0.0


def test_seq_based_detection_survives_a_dropped_packet_that_would_fool_index_based():
    """True send order 1..10, spaced 2s apart, with a 0.5s delay injected
    at every 3rd packet (seq 3, 6, 9). Packet 3 (the first delayed one)
    is dropped downstream of the watermark relay, exactly the scenario
    the audit flagged: every later arrival's *index* shifts by one, but
    its true *sequence number* doesn't.
    """
    period = 3
    delay_s = 0.5
    detection_fraction = 0.5
    spacing = 2.0

    surviving_seqs = [1, 2, 4, 5, 6, 7, 8, 9, 10]  # 3 is lost
    times = [s * spacing + (delay_s if s % period == 0 else 0.0) for s in surviving_seqs]

    # On this exact data, the old index-based logic would report no
    # detection (a false negative): the loss desynchronizes which gap
    # index it thinks corresponds to a watermarked packet.
    assert _old_index_based_rate(times, period, delay_s, detection_fraction) == 0.0

    obs = SessionObservation(session_id=0, egress_times=times, egress_seq=surviving_seqs)
    adv = WatermarkAdversary(period=period, delay_s=delay_s, detection_fraction=detection_fraction)
    result = adv.attack(_ctx(obs), random.Random(1))
    assert result.metrics["watermark_detection_rate"] == 1.0


def test_seq_based_detection_matches_index_based_when_nothing_is_lost():
    """With no loss, arrival index and true sequence number coincide, so
    both approaches must agree (sanity check that the fix doesn't change
    behavior in the common, loss-free case)."""
    period = 3
    delay_s = 0.5
    detection_fraction = 0.5
    spacing = 2.0

    seqs = list(range(1, 11))
    times = [s * spacing + (delay_s if s % period == 0 else 0.0) for s in seqs]

    old_rate = _old_index_based_rate(times, period, delay_s, detection_fraction)

    obs = SessionObservation(session_id=0, egress_times=times, egress_seq=seqs)
    adv = WatermarkAdversary(period=period, delay_s=delay_s, detection_fraction=detection_fraction)
    result = adv.attack(_ctx(obs), random.Random(1))
    assert result.metrics["watermark_detection_rate"] == old_rate == 1.0


def test_watermark_reports_nan_without_egress_seq():
    obs = SessionObservation(session_id=0, egress_times=[1.0, 2.0, 3.0, 4.0])  # egress_seq left empty
    adv = WatermarkAdversary(period=2, delay_s=0.5)
    result = adv.attack(_ctx(obs), random.Random(1))
    assert result.metrics["watermark_sessions_evaluated"] == 0


def test_watermark_disabled_reports_nan():
    obs = SessionObservation(session_id=0, egress_times=[1.0, 2.0], egress_seq=[1, 2])
    adv = WatermarkAdversary(period=0)
    result = adv.attack(_ctx(obs), random.Random(1))
    import math

    assert math.isnan(result.metrics["watermark_detection_rate"])
