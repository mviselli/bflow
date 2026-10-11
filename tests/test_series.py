"""Time series for the charts: sampled by the engine, bounded, emptied on reset."""

from bflow.core.engine import MAX_SAMPLES, SAMPLE_INTERVAL_TICKS, Engine
from bflow.core.scenarios import fault_scenario
from bflow.server.protocol import ResetCommand, snapshot_message
from bflow.server.runner import Runner


def test_a_sample_every_simulated_second_from_tick_zero_with_the_engines_counts():
    engine = Engine(fault_scenario().layout)
    assert [sample.tick for sample in engine.series] == [0]
    for tick in range(1, 3001):
        engine.step()
        if tick % SAMPLE_INTERVAL_TICKS == 0:
            sample, stats = engine.series[-1], engine.stats()
            assert (sample.tick, sample.time_s) == (stats.tick, stats.time_s)
            assert (sample.in_transit, sample.waiting, sample.correctly_delivered,
                    sample.misdelivered, sample.throughput) == (
                stats.in_transit, stats.waiting, stats.correctly_delivered,
                stats.misdelivered, stats.throughput)
    assert SAMPLE_INTERVAL_TICKS == 20
    assert [sample.tick for sample in engine.series] == list(range(0, 3001, 20))


def test_the_series_keeps_only_the_last_ten_simulated_minutes():
    engine = Engine(fault_scenario().layout)
    for _ in range(13000):
        engine.step()
    assert len(engine.series) == MAX_SAMPLES == 600
    assert engine.series[0].tick == 13000 - (MAX_SAMPLES - 1) * SAMPLE_INTERVAL_TICKS
    assert engine.series[-1].tick == 13000


def test_a_snapshot_carries_only_the_samples_after_the_readers_last_one():
    engine = Engine()
    for _ in range(100):
        engine.step()
    assert [s.tick for s in snapshot_message(engine, running=True).series] == [0, 20, 40, 60, 80, 100]
    assert [s.tick for s in snapshot_message(engine, running=True, after_sample_tick=60).series] == [80, 100]
    assert snapshot_message(engine, running=True, after_sample_tick=100).series == []


def test_a_reset_starts_the_series_over():
    runner = Runner()
    for _ in range(400):
        runner.engine.step()
    assert len(runner.engine.series) == 21
    runner.submit(ResetCommand(type="reset"))
    runner.update()
    assert [sample.tick for sample in runner.engine.series] == [0]
