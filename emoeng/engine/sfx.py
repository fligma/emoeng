"""`.sfxproject` sound documents: chiptune patterns rendered on demand."""

from __future__ import annotations

import json
import math
import wave
from pathlib import Path

import numpy as np

from .audio import SAMPLE_RATE, make_sound

SFX_EXT = ".sfxproject"
FORMAT = "emoeng-sfx"
VERSION = 1

WAVES = ("square", "pulse", "tri", "saw", "sine", "noise")
BITS = (8, 16)
RATES = (22050, 32000, 44100, 48000)
# what Save collapses a project into: (key, label, bits)
FORMATS = (("wav16", "WAV 16-bit", 16), ("wav8", "WAV 8-bit", 8))
DEFAULT_FORMAT = "wav16"
# suffixes the mixer decodes into a wav
IMPORTS = (".wav", ".ogg", ".mp3", ".flac")
STEPS = 16                      # one pattern: sixteen sixteenths, four beats
DEFAULT_BPM = 120
MAX_BPM = 300
MIN_BPM = 30
MAX_SECONDS = 30.0              # a longer project is asking for a wav file
TAIL = 0.2                      # room for the last note to fall away

# one instrument: a wave, a gain and notes
TRACK = {
    "name": "track",
    "wave": "square",
    "gain": 0.5,
    "octave": 0,
    "mute": False,
    "duck": 0.0,                # sidechain depth against `duck_by`
    "duck_by": 0,
    "duck_release": 0.15,
    "notes": (),
}

# a note is [start_step, length_steps, midi, velocity]
NOTE = (0, 1, 72, 1.0)

SAMPLE = {"file": "", "at": 0.0, "gain": 0.9, "pitch": 1.0}

SAMPLE_CACHE = {}


# -- documents ---------------------------------------------------------

def blank(title="sound", kind="sfx"):
    """A new project: one lead line, or bass and lead."""
    tracks = [dict(TRACK, name="lead", wave="square", gain=0.45,
                   notes=[[0, 2, 72, 1.0], [2, 1, 76, 0.9], [3, 1, 72, 0.8]])]
    if str(kind) == "music":
        # four on the floor; the lead pumps against it
        tracks.insert(0, dict(TRACK, name="bass", wave="tri", gain=0.5,
                              octave=-2,
                              notes=[[0, 2, 72, 1.0], [4, 2, 72, 1.0],
                                     [8, 2, 72, 1.0], [12, 2, 72, 0.9]]))
        tracks[1]["duck"] = 0.35      # the lead pumps against the bass
        tracks[1]["duck_by"] = 0
    return {
        "format": FORMAT,
        "version": VERSION,
        "title": str(title),
        "kind": "music" if str(kind) == "music" else "sfx",
        "rate": SAMPLE_RATE,
        "bpm": DEFAULT_BPM,
        "steps": STEPS,
        "bits": 16,
        "loop": str(kind) == "music",
        "tracks": tracks,
        "samples": [],
    }


def _number(value, fallback=0.0, low=None, high=None):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    if not math.isfinite(out):
        return float(fallback)
    if low is not None:
        out = max(low, out)
    if high is not None:
        out = min(high, out)
    return out


def _integer(value, fallback=0, low=None, high=None):
    return int(round(_number(value, fallback, low, high)))


def normalise(raw, title=None):
    """A document with every field filled and in range."""
    doc = blank(title or (raw.get("title") if isinstance(raw, dict) else ""))
    if not isinstance(raw, dict):
        return doc
    doc["title"] = str(raw.get("title") or doc["title"] or "sound")
    doc["kind"] = "music" if str(raw.get("kind")) == "music" else "sfx"
    doc["rate"] = _integer(raw.get("rate"), SAMPLE_RATE, 8000, 96000)
    doc["bpm"] = _integer(raw.get("bpm"), DEFAULT_BPM, MIN_BPM, MAX_BPM)
    doc["steps"] = _integer(raw.get("steps"), STEPS, 4, 256)
    doc["bits"] = 8 if _integer(raw.get("bits"), 16) <= 8 else 16
    doc["loop"] = bool(raw.get("loop", doc["loop"]))
    tracks = []
    for entry in raw.get("tracks") or ():
        if not isinstance(entry, dict):
            continue
        tracks.append(_normalise_track(entry))
    if tracks:
        doc["tracks"] = tracks
    samples = []
    for entry in raw.get("samples") or ():
        if not isinstance(entry, dict):
            continue
        name = Path(str(entry.get("file") or "").replace("\\", "/")).name
        if not name:
            continue
        samples.append({
            "file": name,
            "at": _number(entry.get("at"), 0.0, 0.0, MAX_SECONDS),
            "gain": _number(entry.get("gain"), 0.9, 0.0, 2.0),
            "pitch": _number(entry.get("pitch"), 1.0, 0.25, 4.0),
        })
    doc["samples"] = samples
    return doc


def _normalise_track(entry):
    track = dict(TRACK, notes=[])
    track["name"] = str(entry.get("name") or "track")
    wave = str(entry.get("wave") or "square").lower()
    track["wave"] = wave if wave in WAVES else "square"
    track["gain"] = _number(entry.get("gain"), 0.5, 0.0, 1.5)
    track["octave"] = _integer(entry.get("octave"), 0, -4, 4)
    track["mute"] = bool(entry.get("mute", False))
    track["duck"] = _number(entry.get("duck"), 0.0, 0.0, 1.0)
    track["duck_by"] = _integer(entry.get("duck_by"), 0, 0, 63)
    track["duck_release"] = _number(entry.get("duck_release"), 0.15,
                                    0.01, 2.0)
    for note in entry.get("notes") or ():
        if not isinstance(note, (list, tuple)) or len(note) < 3:
            continue
        track["notes"].append([
            _integer(note[0], 0, 0, 255),
            max(1, _integer(note[1], 1, 1, 256)),
            _integer(note[2], 72, 0, 127),
            _number(note[3] if len(note) > 3 else 1.0, 1.0, 0.0, 1.0),
        ])
    track["notes"] = sorted(track["notes"], key=lambda n: (n[0], n[2]))
    return track


def load(path):
    """Read one `.sfxproject`; raises ValueError when it is not one."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read {path.name}: {exc}") from exc
    if isinstance(raw, dict) and raw.get("format") not in (None, FORMAT):
        raise ValueError(f"{path.name} is not a sound project")
    return normalise(raw, title=path.stem)


def save(path, doc):
    """Write the document as JSON, like every other one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = normalise(doc, title=doc.get("title") if isinstance(doc, dict)
                    else None)
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return path


# -- what a document is worth -----------------------------------------

def track_of(doc, index):
    tracks = doc.get("tracks") or ()
    return tracks[index] if 0 <= index < len(tracks) else None


def step_seconds(doc):
    bpm = _number(doc.get("bpm"), DEFAULT_BPM, MIN_BPM, MAX_BPM)
    return 60.0 / bpm / 4.0          # four sixteenths to the beat


def note_count(doc):
    return sum(len(track.get("notes") or ()) for track in doc.get("tracks")
               or ())


def length(doc):
    """Render length: the grid or last sound, plus tail."""
    step = step_seconds(doc)
    steps = _integer(doc.get("steps"), STEPS, 4, 256)
    seconds = steps * step
    for track in doc.get("tracks") or ():
        for note in track.get("notes") or ():
            seconds = max(seconds, (note[0] + note[1]) * step)
    for sample in doc.get("samples") or ():
        seconds = max(seconds, float(sample.get("at", 0.0)))
    return min(MAX_SECONDS, seconds + TAIL)


def describe(doc):
    return (f"{doc.get('kind', 'sfx')}  {doc.get('bpm')} bpm  "
            f"{doc.get('steps')} steps  {len(doc.get('tracks') or ())} "
            f"tracks  {note_count(doc)} notes")


# -- tone shapes -------------------------------------------------------

def midi_hz(note):
    """A MIDI note number as hertz (69 is A4, 440)."""
    return 440.0 * (2.0 ** ((float(note) - 69.0) / 12.0))


NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_name(note):
    """`C4`-style name for a MIDI number."""
    note = int(max(0, min(127, note)))
    return f"{NAMES[note % 12]}{note // 12 - 1}"


def note_from_name(text, octave=4):
    """A MIDI number from `C4` or `F#3`; None if unreadable."""
    text = str(text or "").strip()
    if not text:
        return None
    name = text[0].upper()
    if name not in NAMES:
        return None
    rest = text[1:]
    if rest.startswith("#") or rest.startswith("s"):
        name += "#"
        rest = rest[1:]
    try:
        octv = int(rest) if rest else int(octave)
    except ValueError:
        return None
    return max(0, min(127, NAMES.index(name) + (octv + 1) * 12))


def _quantise(wave, bits):
    """Chip depth: 8-bit tones snap to 256 steps, 16-bit further."""
    levels = 128.0 if int(bits) <= 8 else 32768.0
    return np.clip(np.round(np.asarray(wave, np.float32) * levels) / levels,
                   -1.0, 1.0)


def wave_shape(kind, freq, count, rate=SAMPLE_RATE, bits=16):
    """`count` samples of one tone, in its chip shape."""
    count = max(1, int(count))
    freq = max(0.0, float(freq))
    t = np.arange(count, dtype=np.float32) / float(rate)
    phase = freq * t                 # in cycles, so the shapes stay cheap
    frac = phase - np.floor(phase)
    kind = str(kind or "square").lower()
    if kind == "square":
        wave = np.where(frac < 0.5, 1.0, -1.0)
    elif kind == "pulse":
        wave = np.where(frac < 0.25, 1.0, -1.0)
    elif kind == "tri":
        wave = 4.0 * np.abs(frac - 0.5) - 1.0
    elif kind == "saw":
        wave = 2.0 * frac - 1.0
    elif kind == "noise":
        # sample-and-hold noise: white steps at the note's own rate
        index = np.floor(phase).astype(np.int64)
        rng = np.random.default_rng((int(freq) * 7919 + 13) % (2 ** 32))
        table = rng.uniform(-1.0, 1.0, int(index.max()) + 2)
        wave = table[index]
    else:
        wave = np.sin(2.0 * math.pi * frac)
    return _quantise(np.asarray(wave, np.float32), bits)


def _envelope(count, rate=SAMPLE_RATE, decay=3.0):
    """Attack, a fall through the note and a short release."""
    count = max(1, int(count))
    t = np.arange(count, dtype=np.float32) / max(1, count - 1)
    env = np.exp(-float(decay) * t).astype(np.float32)
    attack = max(1, min(count, int(0.004 * rate)))
    env[:attack] *= np.linspace(0.0, 1.0, attack, dtype=np.float32)
    release = max(1, min(count, int(0.010 * rate)))
    env[-release:] *= np.linspace(1.0, 0.0, release, dtype=np.float32)
    return env


# -- imported wavs -----------------------------------------------------

def format_bits(key):
    """Chip depth behind a Save format key; 16 if unknown."""
    for name, _label, bits in FORMATS:
        if name == str(key):
            return bits
    return 16


def format_label(key):
    """A Save format key as the dialog spells it."""
    for name, label, _bits in FORMATS:
        if name == str(key):
            return label
    return FORMATS[0][1]


def format_of(label):
    """A dialog label or a key, back to its key."""
    text = str(label or "")
    for name, shown, _bits in FORMATS:
        if text in (name, shown):
            return name
    return DEFAULT_FORMAT


def read_wav(path):
    """Mono floats and rate from a wav of any depth."""
    try:
        with wave.open(str(path), "rb") as w:
            rate = w.getframerate()
            channels = w.getnchannels()
            width = w.getsampwidth()
            raw = w.readframes(w.getnframes())
    except (wave.Error, OSError, EOFError):
        return None, 0
    if not raw:
        return None, rate
    if width == 1:
        # an 8-bit wav is unsigned, centred on 128
        data = (np.frombuffer(raw, np.uint8).astype(np.float32)
                - 128.0) / 127.0
    elif width == 2:
        data = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    elif width == 3:
        block = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        packed = block[:, 0] | (block[:, 1] << 8) | (block[:, 2] << 16)
        data = ((packed << 8) >> 8).astype(np.float32) / 8388608.0
    elif width == 4:
        data = np.frombuffer(raw, np.int32).astype(np.float32) / 2147483648.0
    else:
        return None, rate
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return np.ascontiguousarray(data, np.float32), rate


def read_audio(path):
    """Mono floats and rate from any file the mixer decodes;
    a wav reads straight and ogg goes through pygame."""
    data, rate = read_wav(path)
    if data is not None:
        return data, rate
    try:
        import pygame
    except ImportError:
        return None, 0
    started = False
    if not pygame.mixer.get_init():
        try:
            pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=2)
            started = True
        except pygame.error:
            return None, 0
    try:
        sound = pygame.mixer.Sound(str(path))
        raw = pygame.sndarray.array(sound)
        rate = int(pygame.mixer.get_init()[0])
        channels = int(pygame.mixer.get_init()[2])
    except (pygame.error, ValueError):
        return None, 0
    finally:
        if started:
            pygame.mixer.quit()
    if raw is None or not len(raw):
        return None, 0
    flat = raw.astype(np.float32) / 32768.0
    if channels > 1 and flat.ndim > 1:
        flat = flat.reshape(-1, channels).mean(axis=1)
    else:
        flat = flat.reshape(-1)
    return np.ascontiguousarray(flat, np.float32), rate


def import_audio(source, folder):
    """Copy an audio file into `folder` as a wav.
    A wav keeps its bits; the rest is 16-bit wav."""
    source = Path(source)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{source.stem}.wav"
    if source.suffix.lower() == ".wav":
        if source.resolve() != target.resolve():
            target.write_bytes(source.read_bytes())
        return target
    data, rate = read_audio(source)
    if data is None:
        raise ValueError(f"{source.name} cannot be decoded")
    return _write_wav(target, data, rate or SAMPLE_RATE)


def sample_data(sample, audio_dir=None, rate=SAMPLE_RATE):
    """One imported wav as mono float at `rate`, pitched, cached."""
    name = Path(str(sample.get("file") or "").replace("\\", "/")).name
    if not name:
        return None
    path = Path(audio_dir) / name if audio_dir is not None else Path(name)
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return None
    pitch = _number(sample.get("pitch"), 1.0, 0.25, 4.0)
    key = (str(path), mtime, rate, round(pitch, 4))
    if key in SAMPLE_CACHE:
        return SAMPLE_CACHE[key]
    raw, source = read_wav(path)
    out = None
    if raw is not None and source:
        # pitch is a resample: the same samples, sped or slowed
        span = max(1, int(len(raw) * (float(source) / rate) / pitch))
        out = np.interp(np.linspace(0.0, len(raw) - 1.0, span),
                        np.arange(len(raw)), raw).astype(np.float32)
    SAMPLE_CACHE[key] = out
    return out


# -- the render --------------------------------------------------------

def _render_track(track, doc, rate, total, bits):
    out = np.zeros(total, np.float32)
    notes = track.get("notes") or ()
    if not notes:
        return out
    step = step_seconds(doc)
    gain = _number(track.get("gain"), 0.5, 0.0, 1.5)
    octave = _integer(track.get("octave"), 0, -4, 4) * 12
    wave_kind = track.get("wave") or "square"
    for start, span, midi, velocity in notes:
        begin = int(start * step * rate)
        if begin >= total:
            continue
        count = min(total - begin, max(1, int(span * step * rate)))
        tone = wave_shape(wave_kind, midi_hz(midi + octave), count, rate, bits)
        out[begin:begin + count] += \
            tone * (gain * float(velocity)) * _envelope(count, rate)
    return out


def _ducking(track, doc, rate, total, depth, release):
    """1 where quiet, 1 - depth where the source sounds."""
    env = np.ones(total, np.float32)
    step = step_seconds(doc)
    for note in track.get("notes") or ():
        begin = int(note[0] * step * rate)
        if begin >= total:
            continue
        end = min(total, begin + max(1, int(note[1] * step * rate)))
        env[begin:end] = np.minimum(env[begin:end], 1.0 - depth)
        tail = min(total, end + max(1, int(release * rate)))
        if tail > end:
            # the way back up is the pump
            ramp = np.linspace(1.0 - depth, 1.0, tail - end, dtype=np.float32)
            env[end:tail] = np.minimum(env[end:tail], ramp)
    return env


def render(doc, rate=None, audio_dir=None):
    """The whole document as one mono float32 buffer."""
    doc = normalise(doc)
    rate = int(rate or doc.get("rate") or SAMPLE_RATE)
    total = max(1, int(length(doc) * rate))
    bits = int(doc.get("bits") or 16)
    mix = np.zeros(total, np.float32)
    for index, track in enumerate(doc.get("tracks") or ()):
        if track.get("mute"):
            continue
        part = _render_track(track, doc, rate, total, bits)
        depth = _number(track.get("duck"), 0.0, 0.0, 1.0)
        source = track_of(doc, _integer(track.get("duck_by"), 0))
        if depth > 0.0 and source is not None and source is not track:
            # the tone generator's sidechain: this part ducks under another
            part *= _ducking(source, doc, rate, total, depth,
                             _number(track.get("duck_release"), 0.15,
                                     0.01, 2.0))
        mix += part
    for sample in doc.get("samples") or ():
        data = sample_data(sample, audio_dir, rate)
        if data is None:
            continue
        at = int(_number(sample.get("at"), 0.0, 0.0) * rate)
        if at >= total:
            continue
        count = min(total - at, len(data))
        mix[at:at + count] += data[:count] * _number(sample.get("gain"), 0.9,
                                                     0.0, 2.0)
    peak = float(np.abs(mix).max()) if total else 0.0
    if peak > 0.99:
        mix *= 0.99 / peak           # summed tracks never ship clipping
    return mix


def _write_wav(path, data, rate, bits=16):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    clip = np.clip(np.asarray(data, np.float32), -1.0, 1.0)
    if int(bits) <= 8:
        pcm = (clip * 127.0 + 128.0).astype(np.uint8).tobytes()
        width = 1
    else:
        pcm = (clip * 32767.0).astype(np.int16).tobytes()
        width = 2
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(width)
        w.setframerate(int(rate))
        w.writeframes(pcm)
    return path


def write_wav(path, doc, audio_dir=None, bits=None):
    """Render a document to a mono wav; returns the path."""
    doc = normalise(doc)
    rate = int(doc.get("rate") or SAMPLE_RATE)
    depth = int(bits or doc.get("bits") or 16)
    return _write_wav(path, render(doc, rate=rate, audio_dir=audio_dir),
                      rate, depth)


def flatten(path, out=None, audio_dir=None, bits=None):
    """Render one project beside itself; returns (wav path, seconds)."""
    path = Path(path)
    doc = load(path)
    rate = int(doc.get("rate") or SAMPLE_RATE)
    data = render(doc, rate=rate,
                  audio_dir=Path(audio_dir) if audio_dir is not None
                  else path.parent)
    target = Path(out) if out is not None else path.with_suffix(".wav")
    _write_wav(target, data, rate, int(bits or doc.get("bits") or 16))
    return target, len(data) / float(rate)


def sound(path_or_doc, audio_dir=None, settings=None):
    """A mixer Sound from a path or document, to preview."""
    doc = load(path_or_doc) if isinstance(path_or_doc, (str, Path)) \
        else path_or_doc
    return make_sound(render(doc, audio_dir=audio_dir), settings)


def flatten_folder(folder):
    """Collapse one `audio/` folder's projects to wav beside them."""
    folder = Path(folder)
    lines = []
    if not folder.is_dir():
        return lines
    for path in sorted(folder.glob(f"*{SFX_EXT}")):
        try:
            wav, seconds = flatten(path, audio_dir=folder)
        except (OSError, ValueError, wave.Error) as exc:
            lines.append(f"sfx {path.stem}: cannot render ({exc})")
            continue
        try:
            path.unlink()
        except OSError as exc:
            lines.append(f"sfx {path.stem}: {wav.name} written, the project "
                         f"file stayed ({exc})")
            continue
        lines.append(f"sfx {path.stem}: {wav.name} {seconds:.2f}s")
    return lines
