"""Audio-Engine: Vollduplex-Stream, Ringpuffer, Generator, Einzelwiedergabe.

Zwei Backends mit identischer Schnittstelle:
* ``AudioEngine`` – echtes Audio-Interface über PortAudio (sounddevice)
* ``SimulatedEngine`` – virtueller Raum zum Testen ohne Hardware
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np
from .._lazy import signal

from ..dsp.generator import Generator

SIMULATION = "Simulation (ohne Hardware)"


@dataclass
class AudioConfig:
    input_device: str = SIMULATION      # Gerätename oder SIMULATION
    output_device: str | None = None   # None = kein Ausgang
    host_api: str = ""
    samplerate: int = 48000
    blocksize: int = 1024
    input_channels: int = 2
    output_channels: int = 2


class RingBuffer:
    """Mehrkanal-Ringpuffer mit absolutem Sample-Zähler."""

    def __init__(self, channels: int, size: int):
        self.size = size
        self.channels = channels
        self.buf = np.zeros((size, channels), dtype=np.float32)
        self.total = 0
        self.lock = threading.Lock()

    def write(self, block: np.ndarray) -> None:
        n = len(block)
        if n >= self.size:
            block, n = block[-self.size:], self.size
        with self.lock:
            i = self.total % self.size
            first = min(n, self.size - i)
            self.buf[i:i + first] = block[:first]
            if first < n:
                self.buf[: n - first] = block[first:]
            self.total += n

    def _read(self, start: int, end: int, ch=None) -> np.ndarray:
        """Samples [start, end); ``ch`` = Kanalindex (liefert 1-D) oder None (alle Kanäle).

        Nur den gewünschten Kanal zu kopieren spart bei Interfaces mit vielen Eingängen viel
        Speicherbandbreite (z. B. 18 Kanäle: 1/18 der Daten je Bild).
        """
        n = end - start
        i = start % self.size
        first = min(n, self.size - i)
        cols = slice(None) if ch is None else (list(ch) if isinstance(ch, (tuple, list)) else ch)
        width = () if isinstance(cols, int) else ((self.channels,) if ch is None else (len(cols),))
        out = np.empty((n,) + width, dtype=np.float32)
        out[:first] = self.buf[i:i + first][:, cols]       # erst Zeilen, dann Spalten: kopiert nur das Nötige
        if first < n:
            out[first:] = self.buf[: n - first][:, cols]
        return out

    def latest(self, n: int, ch=None) -> np.ndarray:
        with self.lock:
            n = min(n, self.size)
            end = self.total
            start = end - n
            if start < 0:
                shape = (n,) if isinstance(ch, int) else (n, self.channels if ch is None else len(ch))
                out = np.zeros(shape, dtype=np.float32)
                if end:
                    out[-end:] = self._read(0, end, ch)
                return out
            return self._read(start, end, ch)

    def since(self, pos: int) -> tuple[np.ndarray, int]:
        """Alle neuen Samples seit ``pos`` (für lückenlose Verarbeitung)."""
        with self.lock:
            end = self.total
            start = max(pos, end - self.size)
            return self._read(start, end), end

    def range(self, start: int, end: int, ch=None) -> np.ndarray | None:
        with self.lock:
            if start < self.total - self.size or end > self.total or start < 0:
                return None
            return self._read(start, end, ch)


class _OneShot:
    def __init__(self, data: np.ndarray, channels: list[int]):
        self.data = data
        self.channels = channels
        self.pos = 0
        self.start_total: int | None = None


class BaseEngine:
    # längste Aufnahme: Sweep 10 s + Ausklingen 15 s = 25 s → 30 s reichen (halbiert den Speicher;
    # bei 18 Eingängen und 48 kHz ≈ 104 MB statt 207 MB)
    BUFFER_SECONDS = 30

    def __init__(self, config: AudioConfig):
        self.config = config
        self.fs = config.samplerate
        self.ring = RingBuffer(config.input_channels, int(self.BUFFER_SECONDS * self.fs))
        self.generator: Generator | None = None
        self.generator_channels: list[int] = [0]
        self.fade_s = 0.5               # Ein-/Ausblendzeit des Generators
        self._gain = 0.0                # aktuelle Generator-Verstärkung 0…1
        self._target = 0.0
        self._fade_override: float | None = None
        self._oneshot: _OneShot | None = None
        self._lock = threading.Lock()
        self.running = False
        self.peak = np.zeros(config.input_channels)  # letzte Spitzenwerte je Kanal
        self.xruns = 0
        self.output_underruns = 0       # Ausgabe kam zu spät → hörbare Aussetzer im Generator

    # --- im Audio-Thread ---------------------------------------------------
    def _render_output(self, frames: int, nch: int) -> np.ndarray:
        out = np.zeros((frames, nch), dtype=np.float32)
        with self._lock:
            gen, chans, shot = self.generator, self.generator_channels, self._oneshot
            g0, target = self._gain, self._target
            fade = self._fade_override or self.fade_s
        if shot is not None:
            if shot.start_total is None:
                shot.start_total = self.ring.total
            chunk = shot.data[shot.pos: shot.pos + frames]
            for c in shot.channels:
                if c < nch:
                    out[: len(chunk), c] = chunk
            shot.pos += frames
        elif gen is not None:
            # lineare Rampe Richtung Ziel – kein Knacken beim Ein-/Ausschalten
            step = frames / max(1.0, fade * self.fs)
            g1 = min(target, g0 + step) if target > g0 else max(target, g0 - step)
            sig = (gen.render(frames) * np.linspace(g0, g1, frames)).astype(np.float32)
            for c in chans:
                if c < nch:
                    out[:, c] = sig
            with self._lock:
                if self.generator is gen:
                    self._gain = g1
                    if g1 <= 0.0 and self._target <= 0.0:
                        self.generator = None
                        self._fade_override = None
        np.clip(out, -1, 1, out=out)
        return out

    def _on_input(self, block: np.ndarray) -> None:
        self.ring.write(block)
        self.peak = np.maximum(self.peak * 0.0, np.abs(block).max(axis=0))

    # --- Steuerung -----------------------------------------------------------
    def set_generator(self, gen: Generator | None, channels: list[int]) -> None:
        """Generator setzen (blendet ein) oder mit ``None`` ausblenden."""
        with self._lock:
            self._fade_override = None
            if gen is None:
                self._target = 0.0
                if self._gain <= 0.0:
                    self.generator = None
                return
            if self.generator is None:
                self._gain = 0.0
            self.generator = gen
            self.generator_channels = list(channels)
            self._target = 1.0

    def mute(self) -> None:
        """Sofort (20 ms) stumm schalten."""
        with self._lock:
            self._target = 0.0
            self._fade_override = 0.02
            if self._gain <= 0.0:
                self.generator = None

    @property
    def generator_active(self) -> bool:
        return self.generator is not None and self._target > 0

    def play_and_record(self, data: np.ndarray, out_channels: list[int], tail_s: float = 2.0,
                        cancel: threading.Event | None = None) -> np.ndarray:
        """Spielt ``data`` einmal ab und liefert die zeitgleich aufgenommenen Eingänge."""
        if not self.has_output:
            raise RuntimeError("Kein Ausgabegerät gewählt – Messsignal kann nicht abgespielt werden.")
        shot = _OneShot(np.asarray(data, np.float32), out_channels)
        with self._lock:
            self._oneshot = shot
        try:
            need = len(data) + int(tail_s * self.fs)
            deadline = time.monotonic() + need / self.fs + 5.0
            while True:
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("Messung abgebrochen")
                if shot.start_total is not None and self.ring.total >= shot.start_total + need:
                    break
                if time.monotonic() > deadline or not self.running:
                    raise TimeoutError("Audio-Stream liefert keine Daten")
                time.sleep(0.02)
            rec = self.ring.range(shot.start_total, shot.start_total + need)
            if rec is None:
                raise RuntimeError("Aufnahmepuffer übergelaufen")
            return rec
        finally:
            with self._lock:
                if self._oneshot is shot:
                    self._oneshot = None

    @property
    def has_output(self) -> bool:
        return True

    def start(self) -> None: ...
    def stop(self) -> None: ...


class AudioEngine(BaseEngine):
    def __init__(self, config: AudioConfig):
        super().__init__(config)
        import sounddevice as sd  # erst hier, damit Tests ohne PortAudio laufen
        self._sd = sd
        self._stream = None
        self._out_stream = None
        self.duplex = True

    @property
    def has_output(self) -> bool:
        return self.config.output_device is not None

    def _count(self, status) -> None:
        if status:
            self.xruns += 1
            if status.output_underflow:
                self.output_underruns += 1

    def _callback_duplex(self, indata, outdata, frames, time_info, status):
        self._count(status)
        self._on_input(indata.copy())
        outdata[:] = self._render_output(frames, outdata.shape[1])

    def _callback_input(self, indata, frames, time_info, status):
        self._count(status)
        self._on_input(indata.copy())

    def _callback_output(self, outdata, frames, time_info, status):
        self._count(status)
        outdata[:] = self._render_output(frames, outdata.shape[1])

    def _resolve(self, name: str, kind: str) -> int:
        """Gerätename + Host-API → eindeutiger PortAudio-Index."""
        apis = [a["name"] for a in self._sd.query_hostapis()]
        for i, d in enumerate(self._sd.query_devices()):
            if d["name"] == name and d[f"max_{kind}_channels"] > 0 and (
                    not self.config.host_api or apis[d["hostapi"]] == self.config.host_api):
                return i
        raise ValueError(f"Gerät nicht gefunden: {name} ({self.config.host_api})")

    def start(self) -> None:
        """Gleiches Gerät für Ein- und Ausgang → ein Vollduplex-Stream (sample-genau).

        Verschiedene Geräte (z. B. unter macOS „MacBook-Mikrofon“ + „MacBook-Lautsprecher“ oder
        USB-Mikrofon + Kopfhörer) laufen als zwei getrennte Streams: Ein gemeinsamer Stream über
        zwei Geräte mit eigenen Taktquellen bleibt bei Core Audio teilweise stumm oder stockt.
        Für die Impulsantwort gleicht dann die Loopback-Referenz die Latenz aus.
        """
        c = self.config
        dev_in = self._resolve(c.input_device, "input")
        common = dict(samplerate=c.samplerate, blocksize=c.blocksize, dtype="float32", latency="low")
        streams = []
        try:
            if self.has_output:
                dev_out = self._resolve(c.output_device, "output")
                self.duplex = dev_in == dev_out
                if self.duplex:
                    streams.append(self._sd.Stream(device=(dev_in, dev_out),
                                                   channels=(c.input_channels, c.output_channels),
                                                   callback=self._callback_duplex, **common))
                else:
                    streams.append(self._sd.InputStream(device=dev_in, channels=c.input_channels,
                                                        callback=self._callback_input, **common))
                    streams.append(self._sd.OutputStream(device=dev_out, channels=c.output_channels,
                                                         callback=self._callback_output, **common))
            else:
                streams.append(self._sd.InputStream(device=dev_in, channels=c.input_channels,
                                                    callback=self._callback_input, **common))
            for s in streams:
                s.start()
        except Exception:
            for s in streams:
                s.close()
            raise
        self._stream = streams[0]
        self._out_stream = streams[1] if len(streams) > 1 else None
        self.running = True

    def stop(self) -> None:
        self.running = False
        for s in (self._out_stream, self._stream):
            if s is not None:
                s.stop()
                s.close()
        self._stream = self._out_stream = None


class SimulatedEngine(BaseEngine):
    """Virtueller Messaufbau.

    Ausgang 1 speist einen Lautsprecher in einem Raum (≈0.9 s Nachhall, 8 ms
    Laufzeit). Eingang 1 = Messmikrofon, Eingang 2 = Loopback-Referenz.
    Grundgeräusch ≈ 35 dB SPL bei Kalibrierung 0 dBFS = 120 dB SPL.
    """

    BLOCK = 1024

    def __init__(self, config: AudioConfig):
        config.input_channels = 2
        config.output_channels = 2
        config.output_device = config.output_device or SIMULATION
        super().__init__(config)
        self.ir = self._make_room_ir(self.fs)
        self._nfft = 1 << (self.BLOCK + len(self.ir) - 2).bit_length()
        self._irf = np.fft.rfft(self.ir, self._nfft)
        self._tail = np.zeros(len(self.ir) - 1)
        self._noise_sos = signal.butter(1, 200, "lowpass", fs=self.fs, output="sos")
        self._noise_zi = np.zeros((1, 2, 2))  # (Sektionen, 2, Kanäle)
        self._thread: threading.Thread | None = None
        self._rng = np.random.default_rng()

    @staticmethod
    def _make_room_ir(fs: float) -> np.ndarray:
        rng = np.random.default_rng(42)
        n = int(1.6 * fs)
        t = np.arange(n) / fs
        delay = int(0.008 * fs)
        tail = np.zeros(n)
        # frequenzabhängiger Nachhall: tiefe Frequenzen klingen länger
        for fc, t60 in [(125, 1.3), (500, 1.0), (2000, 0.85), (8000, 0.55)]:
            sos = signal.butter(2, [fc / 2 ** 0.5, min(fc * 2 ** 0.5, fs / 2 * 0.95)],
                                "bandpass", fs=fs, output="sos")
            band = signal.sosfilt(sos, rng.standard_normal(n))
            tail += band * np.exp(-6.91 * t / t60)
        tail *= 0.03 * (t > 0.012)  # Direktschall ≈ Nachhall (typische FOH-Position)
        ir = np.zeros(n)
        ir[delay] = 1.0
        for d_ms, g in [(4.1, 0.45), (7.3, -0.3), (11.8, 0.25), (19.0, 0.2)]:
            ir[delay + int(d_ms * 1e-3 * fs)] += g
        ir += np.roll(tail, delay)
        # Lautsprecher: Hochpass 70 Hz, Tiefpass 16 kHz, leichte Senke bei 2.5 kHz
        ir = signal.sosfilt(signal.butter(2, 70, "highpass", fs=fs, output="sos"), ir)
        ir = signal.sosfilt(signal.butter(2, 16000, "lowpass", fs=fs, output="sos"), ir)
        b, a = signal.iirpeak(2500, 2.0, fs)
        ir = ir - 0.35 * signal.lfilter(b, a, ir)
        return ir * 0.5

    def _loop(self) -> None:
        period = self.BLOCK / self.fs
        next_t = time.perf_counter()
        while self.running:
            out = self._render_output(self.BLOCK, 2)
            x = out[:, 0].astype(float)
            y = np.fft.irfft(np.fft.rfft(x, self._nfft) * self._irf, self._nfft)[: self.BLOCK + len(self._tail)]
            y[: len(self._tail)] += self._tail
            mic = y[: self.BLOCK]
            self._tail = y[self.BLOCK: self.BLOCK + len(self._tail)].copy()
            noise, self._noise_zi = signal.sosfilt(
                self._noise_sos, self._rng.standard_normal((self.BLOCK, 2)) * 0.02,
                axis=0, zi=self._noise_zi)
            mic = mic + noise[:, 0] * 10 ** (-60 / 20) * 50 + self._rng.standard_normal(self.BLOCK) * 10 ** (-88 / 20)
            ref = x + self._rng.standard_normal(self.BLOCK) * 10 ** (-100 / 20)
            self._on_input(np.column_stack([mic, ref]).astype(np.float32))
            next_t += period
            delay = next_t - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            elif delay < -0.5:  # stark im Rückstand → neu synchronisieren
                next_t = time.perf_counter()
                self.xruns += 1

    def start(self) -> None:
        self.running = True
        self._thread = threading.Thread(target=self._loop, name="SimAudio", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.running = False
        if self._thread is not None:
            self._thread.join(timeout=1)
            self._thread = None


def create_engine(config: AudioConfig) -> BaseEngine:
    if config.input_device == SIMULATION:
        return SimulatedEngine(config)
    return AudioEngine(config)


def list_devices() -> tuple[list[str], list[dict]]:
    """(Host-API-Namen, Geräteliste mit Namen/Kanälen/Host-API)."""
    import sounddevice as sd
    apis = [a["name"] for a in sd.query_hostapis()]
    devs = []
    for d in sd.query_devices():
        devs.append({
            "name": d["name"], "hostapi": apis[d["hostapi"]],
            "inputs": d["max_input_channels"], "outputs": d["max_output_channels"],
            "samplerate": d["default_samplerate"],
        })
    return apis, devs
