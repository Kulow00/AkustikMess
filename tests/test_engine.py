import time

import numpy as np

from akustik.audio.engine import AudioConfig, RingBuffer, SimulatedEngine, SIMULATION
from akustik.dsp import impulse, room, transfer
from akustik.dsp.generator import PinkNoise


def test_ringbuffer_wraps_and_tracks_position():
    rb = RingBuffer(2, 10)
    rb.write(np.arange(16, dtype=np.float32).reshape(8, 2))
    rb.write(np.arange(16, 24, dtype=np.float32).reshape(4, 2))
    assert rb.total == 12
    assert np.array_equal(rb.latest(3)[:, 0], [18, 20, 22])
    data, pos = rb.since(9)
    assert pos == 12 and len(data) == 3
    assert rb.range(0, 2) is None  # bereits überschrieben


def test_simulation_transfer_function_and_ir():
    eng = SimulatedEngine(AudioConfig(input_device=SIMULATION))
    eng.start()
    try:
        # Übertragungsfunktion mit rosa Rauschen: Laufzeit ≈ 8 ms finden
        eng.set_generator(PinkNoise(eng.fs, -12), [0])
        time.sleep(1.5)
        buf = eng.ring.latest(eng.fs).astype(float)
        d = transfer.find_delay(buf[:, 1], buf[:, 0], max_delay=eng.fs // 2)
        assert abs(d / eng.fs - 0.008) < 0.0005
        eng.set_generator(None, [0])
        # Sweep-Messung mit Loopback-Referenz
        sweep = impulse.exp_sweep(20, 20000, 1.0, eng.fs) * 0.5
        rec = eng.play_and_record(sweep, [0], tail_s=1.6)
        h = impulse.deconvolve(rec[:, 0], rec[:, 1], eng.fs)
        res = {r.label: r for r in room.analyze(h[: int(1.8 * eng.fs)], eng.fs)}
        assert 0.8 < res["1k"].t30 < 1.2
    finally:
        eng.stop()
