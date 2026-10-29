# Audio

`engine.audio` is a named sound bank plus a numpy synth. The mixer is opened
once by `Game`, and a scene says `self.audio.play("step")` rather than holding
`Sound` objects. A project can ship a full soundtrack without owning a single
`.wav`, because tones are generated at run time.

## What the game sets up

| Step | Detail |
| --- | --- |
| `pygame.mixer.pre_init(44100, -16, 2, 512)` | Before `pygame.init()`, so the buffer is small and latency low |
| `Audio(master=..., music_volume=...)` | `pygame.mixer.init(44100, -16, 2, 512)` if needed, then `set_num_channels(32)` |
| `build_starter_kit(audio)` | Adds the six stock effects |
| `project.load_audio(audio)` | Loads `audio/` and applies this project's import gains |
| `runtime.master_volume` / `runtime.music_volume` | Config defaults `0.8` / `0.6`; re-applied by `game.reload_config()` |
| `game.run()`'s `finally` | `audio.stop_all()` on exit |

If the mixer cannot open - no sound device, a headless test - `audio.ok` is
`False` and every call returns quietly. Audio is never a reason a game fails to
start.

## `Audio` API

| Group | Member | Signature |
| --- | --- | --- |
| State | `ok` | `bool` - is the mixer live |
| State | `settings` | `(rate, format, channels)` in use |
| State | `sounds` / `volumes` / `gains` | The bank, the last requested volumes, the import gains |
| Loading | `load` | `load(key, path, gain=1.0)` - cache a file under a short name |
| Loading | `load_folder` | `load_folder(folder, gain=1.0)` - every `.wav/.ogg/.mp3/.flac`, plus every `.sfxproject` rendered on the spot, keyed by file stem; returns the stems loaded |
| Loading | `set_gain` / `gain` | `set_gain(key, gain)` clamped `0..4`; a bad value keeps the old one |
| Loading | `add_sound` / `sound` | `add_sound(key, snd)` file a hand-built `Sound`; `sound(key)` fetch it |
| Playback | `play` | `play(key, volume=1.0, loops=0)` - `loops=-1` repeats; returns the channel or `None` |
| Playback | `play_at` | `play_at(key, pos, listener, volume=1.0, max_dist=45.0)` - distance-attenuated |
| Playback | `stop` / `stop_all` | Halt every channel; `stop_all` also fades music out over 200 ms |
| Music | `music` | `music(path, volume=None, loop=True, fade_ms=500)` - the streaming track; returns `True` if it started |
| Music | `set_music_volume` / `stop_music` | `set_music_volume(v)`; `stop_music(fade_ms=400)` |
| Music | `music_key` | The stem of the track now playing, or `None` |
| Master | `set_master` | `set_master(volume)` - re-applies to the music and to every sound already playing |
| Master | `quit` | Stop the music and close the mixer |
| Synth | `tone` | `tone(key, freq=440.0, ms=180.0, kind="sine", volume=0.4, decay=True)` |
| Synth | `sweep` | `sweep(key, f0=220.0, f1=880.0, ms=400.0, volume=0.35, kind="sine")` |
| Synth | `noise` | `noise(key, ms=140.0, volume=0.3, smooth=0.5, seed=1)` |

Final loudness is `volume * gain(key) * master`, clamped to `0..1`; a result of
`0` is not played at all. `volume` is remembered per key, so `set_master()`
retunes what is already sounding.

## The synth, on its own

| Function | Signature | Output |
| --- | --- | --- |
| `synth` | `synth(freq=440.0, ms=180.0, kind="sine", volume=0.4, rate=44100, decay=True)` | `float32` mono samples; `kind` is `sine`, `square`, `saw`, `tri` |
| `synth_sweep` | `synth_sweep(f0=220.0, f1=880.0, ms=400.0, volume=0.35, kind="sine", rate=44100)` | A frequency glide, `sine` or `square` |
| `synth_noise` | `synth_noise(ms=140.0, volume=0.3, smooth=0.5, seed=1, rate=44100)` | Filtered noise; `smooth` `0..0.95` darkens it, `seed` makes it repeatable |
| `make_sound` | `make_sound(samples, settings=None)` | `float32` mono - an int16 `pygame.mixer.Sound` in the mixer's own format, stereo-duplicated if needed |

All three envelope with a short attack and a long release, so nothing clicks.
`tone` / `sweep` / `noise` on an `Audio` instance wrap this into the bank and
are idempotent - the second call with the same key returns the cached sound
without rebuilding it.

```python
self.audio.tone("hum", 70.0, 900.0, "sine", 0.18)   # a 900 ms loopable drone
self.hum = self.audio.play("hum", 0.5, loops=-1)
self.audio.sweep("gate", 180.0, 90.0, 700.0, 0.3, "saw")
self.audio.noise("wind", 1200.0, 0.12, smooth=0.9, seed=4)
```

## The stock kit

`build_starter_kit()` fills any empty slot with these, so a brand-new project
has usable effects before it imports anything. Existing keys are never
overwritten, so your own `step.wav` wins.

| Key | What it is |
| --- | --- |
| `ui_click` | 45 ms square blip at 1100 Hz |
| `ui_open` | 110 ms triangle sweep 480 - 900 Hz |
| `step` | 90 ms filtered noise |
| `pickup` | 180 ms sine sweep 660 - 1320 Hz |
| `thud` | 220 ms sine at 90 Hz |
| `beep` | 120 ms square at 880 Hz |

## Files, stems and gains

Anything in the project's `audio/` folder is loaded under its **file stem**:
`audio/gate.ogg` is `play("gate")`. `AUDIO_EXT` is `.wav`, `.ogg`, `.mp3`,
`.flac`. A `.sfxproject` in the same folder is loaded the same way, from a
render rather than a file - see the next section.

| `assets.json` key | Effect |
| --- | --- |
| `"audio": {"gain": 1.0}` | One import gain for the whole folder |
| `"audio": {"gains": {"step": 0.6}}` | Per-stem overrides, applied after the folder gain |

```json
{
 "format": 1,
 "audio": { "gain": 1.0, "gains": { "step": 0.55, "thud": 1.4 } }
}
```

The Audio tab writes this file; see [The Editor](editor.md).

## Sound projects

A `.sfxproject` in `audio/` is a pattern the engine renders rather than a file
it reads. The editor's sound maker writes them, and a game can ship one
instead of a wav: `render()` is pure numpy, so the preview, the runtime and a
build produce the same samples.

```json
{
 "format": "emoeng-sfx", "version": 1,
 "title": "theme", "kind": "music", "rate": 44100,
 "bpm": 120, "steps": 16, "bits": 16, "loop": true,
 "tracks": [
  {"name": "bass", "wave": "tri", "gain": 0.5, "octave": -2,
   "notes": [[0, 2, 72, 1.0], [4, 2, 72, 1.0]]},
  {"name": "lead", "wave": "square", "gain": 0.4, "octave": 0,
   "duck": 0.35, "duck_by": 0, "duck_release": 0.15,
   "notes": [[0, 1, 0, 0.9], [2, 1, 3, 0.8]]}
 ],
 "samples": [{"file": "clap.wav", "at": 1.0, "gain": 0.9, "pitch": 1.0}]
}
```

| Field | Detail |
| --- | --- |
| `kind` | `sfx` or `music`; only the maker's template differs |
| `bpm`, `steps` | `step_seconds()` is `60 / (bpm * 4)`; `steps` is the pattern length, sixteen by default |
| `bits` | `8` or `16` - each wave is quantised before it is mixed, so 8-bit is audibly crunchier |
| track `wave` | `sfx.WAVES`: `square`, `pulse`, `tri`, `saw`, `sine`, `noise` |
| track `octave` | added to every note's MIDI number, so a bass part is one number |
| a note | `[start_step, length_steps, midi, velocity]`; `72` is C5 |
| track `duck` | `0..1` sidechain depth: the track dips while `duck_by`'s notes sound and recovers over `duck_release` seconds |
| `samples` | `.wav` files mixed in under the tracks, with `at` in seconds, `gain` and `pitch` |

`render(doc)` sums every unmuted track, multiplies in the ducking envelopes,
adds the samples and scales down only when the peak passes `0.99`, so a
pattern does not clip. The result is mono `float32` at the document's `rate`;
`write_wav()` puts it in a mono 16-bit wav, which is the only format written.

| Function | Does |
| --- | --- |
| `load(path)` / `save(path, doc)` | read and write the JSON, through `normalise()` |
| `blank(title, kind)` | a starting pattern; a `music` one ships a bass line and a ducked lead |
| `length(doc)` / `describe(doc)` | seconds, and the one-line summary the maker puts in its status line |
| `render(doc, rate=None, audio_dir=None)` | the whole pattern as samples |
| `write_wav(path, doc)` / `flatten(path)` | a wav; `flatten` writes beside the project |
| `flatten_folder(folder)` | every project in one `audio/` folder, each replaced by its wav |
| `sound(path_or_doc)` | a mixer `Sound`, which is what the preview plays |
| `read_wav(path)` | `(samples, rate)` from a 16-bit wav; stereo is mixed down to mono |

Three places consume one pattern:

| Where | What happens |
| --- | --- |
| `project.load_audio()` | `load_folder()` renders each project and files it under its stem, so `play("theme")` works with no wav on disk |
| The editor's Save | asks once, writes `audio/<name>.wav` and deletes the project - the wav is the sound from then on |
| `BuildConfig.prepare()` | collapses only the staged copy: the wav appears in `<workpath>/bundle/projects/<name>/audio`, the project file does not, and your own folder keeps the pattern |

Only WAV is written for now. A render is mono 16-bit, there is no `.ogg` or
`.mp3` export, and the maker's Import takes wav files only.

## Distance and 3D

The mixer has no panning, so position becomes loudness: `play_at()` squares the
`(1 - d / max_dist)` falloff and stays silent at or past the limit.

```python
def update(self, dt):
    super().update(dt)
    for mote in self.motes:
        if mote.alive:
            self.audio.play_at("hum", mote.pos, self.player.pos,
                               volume=0.5, max_dist=24.0)
```

For something that should run continuously, play it once with `loops=-1` and
retune the `Sound` instead: `self.audio.sound("drone").set_volume(v)`.

## Music

`music()` streams from disk on its own channel, independent of the bank.

| Fact | Detail |
| --- | --- |
| Volume | `volume` (or `music_volume` from config) scaled by `master` |
| Looping | `loop=True` plays `-1` forever |
| Fades | `fade_ms` on start, `stop_music(fade_ms)` on stop |
| Start-up | Nothing plays until a scene asks - `music()` is called from game code |
| Boot track | `audio.music` names a stem, and `boot_music()` looks only at real files - a pattern has to be collapsed before it can be that track |
| Hot reload | The game remembers `music_key`, re-reads the bank and restarts the same track at `fade_ms=0` |

```python
def setup(self):
    self.audio.music(self.project.dir("audio") / "drone.wav", volume=0.35)

def on_gate_opened(self):
    self.audio.stop_music(800)
    self.audio.music(self.project.dir("audio") / "inside.ogg", fade_ms=800)
```

## Object and scene proxies

| Proxy | Resolves to |
| --- | --- |
| `scene.audio` | `game.audio` |
| `obj.audio` | `scene.audio` |

So a prop plays its own sound without being handed anything. The prop exposes a
method; the scene calls it when the player presses `use`.

```python
class Gem(fe.Object3D):
    def collect(self):
        self.audio.play("pickup")
        self.alive = False


class Main(fe.Scene3D):
    def update(self, dt):
        super().update(dt)
        if self.input.pressed("use") and self.nearby is not None:
            self.nearby.collect()
```

Related pages: [Project Folder](project-folder.md), [Objects](objects.md),
[The Editor](editor.md).
