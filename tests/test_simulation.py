from anontestlab.core.simulation import Simulation


def test_schedule_runs_in_time_order():
    sim = Simulation()
    order = []
    sim.schedule(3, lambda: order.append("c"))
    sim.schedule(1, lambda: order.append("a"))
    sim.schedule(2, lambda: order.append("b"))
    sim.run()
    assert order == ["a", "b", "c"]
    assert sim.now == 3


def test_run_until_stops_early():
    sim = Simulation()
    fired = []
    sim.schedule(1, lambda: fired.append(1))
    sim.schedule(5, lambda: fired.append(5))
    sim.run(until=2)
    assert fired == [1]
    assert sim.now == 2


def test_callback_can_schedule_more_events():
    sim = Simulation()
    count = []

    def tick(n=0):
        count.append(n)
        if n < 3:
            sim.schedule(1, lambda: tick(n + 1))

    sim.schedule(0, tick)
    sim.run()
    assert count == [0, 1, 2, 3]
