"""Audio for fligengine games: sound files plus a small synth.

The mixer is opened once by the Game (or lazily here). Names are keys, so a
scene says `game.audio.play("step")` instead of juggling Sound objects;
`play_at` attenuates by distance from the listener, which is enough for
PS2-style positional audio (the mixer has no panning).

The synth builds tones, sweeps and noise straight into mixer buffers, so a
project can ship a soundtrack and effects before it owns a single .wav.
"""

import math
from pathlib import Path

import numpy as np
import pygame

SAMPLE_RATE = 44100
AUDIO_EXT = (".wav", ".ogg", ".mp3", ".flac")


class Audio:
    def __init__(self, master=0.8, channels=32):
        self.master = float(master)
        self.ok = False
        self.sounds = {}
        self.volumes = {}
        self.music_key = None
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init(SAMPLE_RATE, -16, 2, 512)
            pygame.mixer.set_num_channels(channels)
            self.ok = True
        except pygame.error:
            self.ok = False
        self.settings = pygame.mixer.get_init() or (SAMPLE_RATE, -16, 2)

    # ------------------------------------------------------------- loading
    def load(self, key, path):
        """Load (and cache) a sound file under a short name."""
        if not self.ok:
            return None
        try:
            snd = pygame.mixer.Sound(str(path))
        except pygame.error:
            return None
        self.sounds[key] = snd
        return snd

    def load_folder(self, folder):
        """Load every audio file in a folder, keyed by file stem."""
        out = []
        folder = Path(folder)
        if not folder.is_dir():
            return out
        for p in sorted(folder.iterdir()):
            if p.suffix.lower() in AUDIO_EXT:
                if self.load(p.stem, p) is not None:
                    out.append(p.stem)
        return out

    def add_sound(self, key, snd):
        if snd is not None:
            self.sounds[key] = snd
        return snd

    def sound(self, key):
        return self.sounds.get(key)

    # ------------------------------------------------------------ playback
    def play(self, key, volume=1.0, loops=0):
        if not self.ok:
            return None
        snd = self.sounds.get(key)
        if snd is None:
            return None
        vol = max(0.0, min(1.0, volume * self.master))
        if vol <= 0.0:
            return None
        ch = snd.play(loops=loops)
        if ch is not None:
            # a channel keeps playing at its own volume; remember the base
            ch.set_volume(vol)
            self.volumes[key] = volume
        return ch

    def play_at(self, key, pos, listener, volume=1.0, max_dist=45.0):
        """Distance-attenuated one-shot; silent past max_dist."""
        d = math.dist(pos, listener)
        if d >= max_dist:
            return None
        att = (1.0 - d / max_dist) ** 2
        return self.play(key, volume=volume * att)

    def stop(self):
        if self.ok:
            pygame.mixer.stop()

    def stop_all(self):
        self.stop()
        self.stop_music(200)

    # --------------------------------------------------------------- music
    def music(self, path, volume=0.6, loop=True, fade_ms=500):
        if not self.ok:
            return False
        try:
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.set_volume(max(0.0, min(1.0,
                                                       volume * self.master)))
            pygame.mixer.music.play(-1 if loop else 0, fade_ms=fade_ms)
            self.music_key = Path(path).stem
            return True
        except pygame.error:
            return False

    def stop_music(self, fade_ms=400):
        if not self.ok:
            return
        self.music_key = None
        try:
            if fade_ms > 0:
                pygame.mixer.music.fadeout(fade_ms)
            else:
                pygame.mixer.music.stop()
        except pygame.error:
            pass

    # -------------------------------------------------------------- master
    def set_master(self, volume):
        self.master = max(0.0, min(1.0, float(volume)))
        if self.ok:
            pygame.mixer.music.set_volume(self.master)
        for key, base in self.volumes.items():
            snd = self.sounds.get(key)
            if snd is not None:
                snd.set_volume(max(0.0, min(1.0, base * self.master)))

    def quit(self):
        if not self.ok:
            return
        try:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except pygame.error:
            pass
        self.ok = False

    # -------------------------------------------------------------- synth
    def tone(self, key, freq=440.0, ms=180.0, kind="sine", volume=0.4,
             decay=True):
        """Cache a synthesised one-shot tone under `key`."""
        if key in self.sounds:
            return self.sounds[key]
        return self.add_sound(key, make_sound(
            synth(freq, ms, kind, volume, decay=decay), self.settings))

    def sweep(self, key, f0=220.0, f1=880.0, ms=400.0, volume=0.35,
              kind="sine"):
        if key in self.sounds:
            return self.sounds[key]
        return self.add_sound(key, make_sound(
            synth_sweep(f0, f1, ms, volume, kind), self.settings))

    def noise(self, key, ms=140.0, volume=0.3, smooth=0.5, seed=1):
        if key in self.sounds:
            return self.sounds[key]
        return self.add_sound(key, make_sound(
            synth_noise(ms, volume, smooth, seed), self.settings))


# --------------------------------------------------------------- synthesis
def _samples(ms, rate):
    return max(1, int(rate * ms / 1000.0))


def _envelope(n, attack=0.01, release=0.35):
    env = np.ones(n, np.float32)
    a = max(1, int(n * attack))
    r = max(1, int(n * release))
    env[:a] = np.linspace(0.0, 1.0, a)
    env[-r:] *= np.linspace(1.0, 0.0, r)
    return env


def synth(freq=440.0, ms=180.0, kind="sine", volume=0.4, rate=SAMPLE_RATE,
          decay=True):
    """One tone. kind: sine / square / saw / tri."""
    n = _samples(ms, rate)
    t = np.arange(n, dtype=np.float32) / rate
    phase = 2.0 * math.pi * freq * t
    if kind == "square":
        wave = np.sign(np.sin(phase))
    elif kind == "saw":
        wave = 2.0 * (t * freq - np.floor(0.5 + t * freq))
    elif kind == "tri":
        wave = 2.0 * np.abs(2.0 * (t * freq - np.floor(0.5 + t * freq))) - 1.0
    else:
        wave = np.sin(phase)
    env = _envelope(n, release=0.5 if decay else 0.05)
    return np.asarray(wave * env * volume, np.float32)


def synth_sweep(f0=220.0, f1=880.0, ms=400.0, volume=0.35, kind="sine",
                rate=SAMPLE_RATE):
    n = _samples(ms, rate)
    t = np.arange(n, dtype=np.float32) / rate
    f = np.linspace(f0, f1, n)
    phase = 2.0 * math.pi * np.cumsum(f) / rate
    wave = np.sign(np.sin(phase)) if kind == "square" else np.sin(phase)
    return np.asarray(wave * _envelope(n, 0.02, 0.5) * volume, np.float32)


def synth_noise(ms=140.0, volume=0.3, smooth=0.5, seed=1, rate=SAMPLE_RATE):
    n = _samples(ms, rate)
    rng = np.random.default_rng(seed)
    raw = rng.normal(0.0, 1.0, n).astype(np.float32)
    k = max(1, int(n * max(0.0, min(0.95, smooth)) * 0.1))
    if k > 1:
        kernel = np.ones(k, np.float32) / k
        raw = np.convolve(raw, kernel, mode="same")
    return np.asarray(raw * _envelope(n, 0.005, 0.7) * volume, np.float32)


def make_sound(samples, settings=None):
    """float32 mono samples -> int16 pygame Sound in the mixer's format."""
    settings = settings or pygame.mixer.get_init() or (SAMPLE_RATE, -16, 2)
    _rate, _fmt, channels = settings
    data = np.clip(np.asarray(samples, np.float32), -1.0, 1.0)
    pcm = (data * 32767.0).astype(np.int16)
    if channels and channels > 1:
        pcm = np.repeat(pcm[:, None], channels, axis=1).reshape(-1)
    return pygame.mixer.Sound(buffer=np.ascontiguousarray(pcm).tobytes())


# --------------------------------------------------------------- stock kit
def build_starter_kit(audio):
    """A tiny effect bank every project can use without asset files."""
    if not audio.ok:
        return audio
    audio.sounds.setdefault("ui_click", make_sound(
        synth(1100.0, 45, "square", 0.22), audio.settings))
    audio.sounds.setdefault("ui_open", make_sound(
        synth_sweep(480.0, 900.0, 110, 0.2, "tri"), audio.settings))
    audio.sounds.setdefault("step", make_sound(
        synth_noise(90, 0.35, 0.85, 3), audio.settings))
    audio.sounds.setdefault("pickup", make_sound(
        synth_sweep(660.0, 1320.0, 180, 0.3, "sine"), audio.settings))
    audio.sounds.setdefault("thud", make_sound(
        synth(90.0, 220, "sine", 0.5), audio.settings))
    audio.sounds.setdefault("beep", make_sound(
        synth(880.0, 120, "square", 0.2), audio.settings))
    return audio
