import threading

from app.write_buffer.buffer import WriteBuffer


def test_concurrent_increments_are_exact():
    b = WriteBuffer()

    def work():
        for i in range(2000):
            b.increment(f"q{i % 50}")

    ts = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    snap = b.flush()
    assert sum(snap.values()) == 8 * 2000 and len(snap) == 50
    assert b.get_size() == 0


def test_flush_is_copy_on_clear():
    b = WriteBuffer()
    b.increment("a")
    b.increment("a")
    s = b.flush()
    b.increment("a")
    assert s == {"a": 2} and b.flush() == {"a": 1}


def test_unique_cap_drops_new_keys_but_keeps_counting_existing():
    b = WriteBuffer(max_unique=2)
    assert b.increment("a") and b.increment("b")
    assert b.increment("c") is False          # new key rejected
    assert b.increment("a") is True           # existing key still counted
    assert b.flush() == {"a": 2, "b": 1}


def test_merge_restores_counts_and_reports_overflow_loss():
    b = WriteBuffer(max_unique=2)
    b.increment("x")
    lost = b.merge({"x": 3, "y": 2, "z": 5})   # y fits, z does not
    assert lost == 5
    assert b.flush() == {"x": 4, "y": 2}


def test_memory_is_bounded_under_unique_flood():
    b = WriteBuffer(max_unique=1000)
    accepted = sum(b.increment(f"u{i}") for i in range(50_000))
    assert accepted == 1000 and b.get_size() == 1000
