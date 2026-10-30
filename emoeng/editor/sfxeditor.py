"""The Audio tab's maker: a step grid over one `.sfxproject`.

The player answers what a sound file sounds like; this view is where the
file comes from. A project is a few tone tracks on a sixteen-step grid,
each with a wave, a gain and a sidechain depth, plus the wavs imported
under them. Saving renders the lot and deletes the document, because the
wav is what a game plays - the tab says so before it writes.
"""

from __future__ import annotations

import copy
import time
from pathlib import Path

import pygame

from ..engine import sfx, xp
from . import widgets

LIST_W = 186                # the project list, as wide as the player's
HEAD_H = 20
BAR_H = 26                  # the button row above the grid
ROW_H = 26                  # one track's row
RULER_H = 16
NAME_W = 90
CELL_MIN = 9
CELL_MAX = 26
SAMPLE_H = 18
UNDO_LIMIT = 40
PREVIEW_VOLUME = 0.8

# one colour per tone shape, so a track reads at a glance
WAVE_COLORS = {
    "square": (74, 118, 202),
    "pulse": (36, 150, 158),
    "tri": (110, 160, 66),
    "saw": (206, 132, 38),
    "sine": (128, 96, 186),
    "noise": (122, 122, 122),
}

STEP_CHOICES = (16, 32, 64)


class SfxEditor:
    """Edit one sound project: tones, sidechain and imported wavs."""

    def __init__(self, app):
        self.app = app
        self.project = None
        self.path = None            # the `.sfxproject` on disk
        self.doc = None             # the document being edited
        self.dirty = False
        self.pending_kind = "sfx"   # what the New dialog is making
        self.track = 0              # the track the buttons act on
        self.step = 0               # the step a placed sample lands on
        self.scroll = 0
        self.message = ""
        self.undo = []
        self.redo = []
        self.buttons = []           # [{"action", "rect"}] drawn this frame
        self.tracks = []            # [(index, rect)] track name cells
        self.cells = []             # [(track, step, rect)] grid cells
        self.sample_rows = []       # [(index, rect)] imported wav rows
        self.file_rows = []         # [(path, rect)] the project list
        self.area = pygame.Rect(0, 0, 0, 0)
        self.list_rect = pygame.Rect(0, 0, 0, 0)
        self.list_head = pygame.Rect(0, 0, 0, 0)
        self.list_body = pygame.Rect(0, 0, 0, 0)
        self.bar = pygame.Rect(0, 0, 0, 0)
        self.ruler = pygame.Rect(0, 0, 0, 0)
        self.grid_rect = pygame.Rect(0, 0, 0, 0)
        self.samples_rect = pygame.Rect(0, 0, 0, 0)
        self.cell = CELL_MAX
        self._sound = None
        self.started = None         # when the preview began, for the playhead
        self._lengths = {}          # path -> (mtime, seconds)
        self.hover_tip = None
        self.hover_pos = (0, 0)
        self.picks = None           # the open tone-shape list
        self._wave_rect = None      # where the Wave button was drawn

    # -- the open document ---------------------------------------------

    def set_project(self, project):
        """A project switch keeps what was written, not what was typed."""
        self.store()
        self.stop()
        self.project = project
        self.path = None
        self.doc = None
        self.dirty = False
        self.undo.clear()
        self.redo.clear()
        self.track = 0
        self._lengths.clear()
        self.scroll = 0

    def open(self, path, force=False):
        """Load one `.sfxproject` for editing."""
        path = Path(path)
        if self.path is not None and path.resolve() == self.path.resolve() \
                and self.doc is not None:
            return True
        if self.dirty and not force:
            self.app.log("sfx: save this project before opening another",
                         "warn")
            return False
        try:
            doc = sfx.load(path)
        except (OSError, ValueError) as exc:
            self.app.log(f"sfx: cannot open {path.name}: {exc}", "error")
            return False
        self.stop()
        self.path = path
        self.doc = doc
        self.dirty = False
        self.track = 0
        self.step = 0
        self.undo.clear()
        self.redo.clear()
        self.message = sfx.describe(doc)
        return True

    def close(self):
        """Forget the open project without writing anything."""
        self.stop()
        self.path = None
        self.doc = None
        self.dirty = False
        self.undo.clear()
        self.redo.clear()

    def new(self, name="sound", kind=None):
        """Write a blank project into `audio/` and open it."""
        project = self.project or self.app.project
        if project is None:
            self.app.log("open a project first", "warn")
            return False
        from .app import clean_stem

        kind = kind or self.pending_kind or "sfx"
        stem = clean_stem(name, "sound")
        path = project.audio_dir / f"{stem}{sfx.SFX_EXT}"
        if path.exists():
            self.app.log(f"audio/{path.name} already exists", "warn")
            return False
        doc = sfx.blank(stem, kind)
        try:
            sfx.save(path, doc)
        except OSError as exc:
            self.app.log(f"cannot make {path.name}: {exc}", "error")
            return False
        self.open(path, force=True)
        self.app.refresh_tree()
        self.message = f"new {kind} {path.name}"
        self.app.status = f"sound {path.name}"
        self.app.log(f"made audio/{path.name}; Save collapses it to "
                     f"{stem}.wav", "ok")
        return True

    def prompt_new(self, kind="sfx"):
        """Ask for a name, then make the project the button asked for."""
        self.pending_kind = "music" if kind == "music" else "sfx"
        music = self.pending_kind == "music"
        self.app.dialog_kind = "sfx_new"
        self.app.dialog = widgets.PromptDialog(
            "New Music Project" if music else "New Sound Project",
            "Name (file stem)", "theme" if music else "sound",
            hint=(f"Writes audio/<name>{sfx.SFX_EXT}: a looping "
                  f"{sfx.STEPS}-step pattern you fill in on the grid"
                  if music else
                  f"Writes audio/<name>{sfx.SFX_EXT}: a short pattern you "
                  "fill in on the grid"), width=430)

    def store(self):
        """Write the pattern back as a project; no flattening."""
        if not self.dirty or self.path is None or self.doc is None:
            return False
        try:
            sfx.save(self.path, self.doc)
        except OSError as exc:
            self.app.log(f"sfx: cannot write {self.path.name}: {exc}",
                         "error")
            return False
        self.dirty = False
        self.app.log(f"sfx: kept audio/{self.path.name} as a project "
                     "(Save collapses it to a wav)", "muted")
        return True

    # -- saving --------------------------------------------------------

    def save(self, force=False, fmt=None):
        """Render the project to a wav and delete the document."""
        if self.doc is None or self.path is None:
            self.message = "no sound project open"
            self.app.log("sfx: no sound project open; New makes one",
                         "warn")
            return False
        if not force:
            self.app.dialog_kind = "sfx_save"
            self.app.dialog = widgets.ChoiceDialog(
                "Collapse to a Sound File",
                f"{self.path.name} becomes {self.path.stem}.wav, and the "
                "sound project is deleted.",
                tuple(label for _key, label, _bits in sfx.FORMATS) + ("Cancel",),
                hint="16-bit keeps the tones clean, 8-bit keeps the chip "
                     "crunch. The project file goes either way, so collapse "
                     "once the sound is finished - a build does the same to "
                     "its bundled copy.", default=0)
            return False
        target = self.path.with_suffix(".wav")
        seconds = sfx.length(self.doc)
        depth = sfx.format_bits(sfx.format_of(fmt or sfx.DEFAULT_FORMAT))
        try:
            sfx.write_wav(target, self.doc, audio_dir=self._audio_dir(),
                          bits=depth)
            self.path.unlink()
        except (OSError, ValueError) as exc:
            self.message = f"cannot collapse: {exc}"
            self.app.log(f"sfx: cannot collapse {self.path.name}: {exc}",
                         "error")
            return False
        name = self.path.name
        self.stop()
        self.path = None
        self.doc = None
        self.dirty = False
        self.undo.clear()
        self.redo.clear()
        self.message = f"collapsed to {target.name}"
        self.app.log(f"collapsed audio/{name} into {target.name} "
                     f"({depth}-bit, {seconds:.2f}s); the project file is "
                     "gone", "ok")
        self.app.media.player.refresh()
        # the wav is the sound now: the player takes over with it loaded
        self.app.media.load(target)
        self.app.status = f"wav {target.name}"
        self.app.refresh_tree()
        self._lengths.clear()
        return True

    # -- what the buttons act on ---------------------------------------

    def current_track(self):
        return sfx.track_of(self.doc, self.track) if self.doc else None

    def _audio_dir(self):
        if self.project is not None:
            return self.project.audio_dir
        return self.path.parent if self.path is not None else None

    def _touch(self, message=""):
        self.dirty = True
        if message:
            self.message = message
            self.app.status = message

    def _push_undo(self):
        if self.doc is None:
            return
        self.undo.append((self.track, self.step, copy.deepcopy(self.doc)))
        if len(self.undo) > UNDO_LIMIT:
            self.undo.pop(0)
        self.redo.clear()

    def undo_step(self):
        if not self.undo:
            return False
        self.redo.append((self.track, self.step, copy.deepcopy(self.doc)))
        self.track, self.step, self.doc = self.undo.pop()
        self.dirty = True
        self.message = "undo"
        return True

    def redo_step(self):
        if not self.redo:
            return False
        self.undo.append((self.track, self.step, copy.deepcopy(self.doc)))
        self.track, self.step, self.doc = self.redo.pop()
        self.dirty = True
        self.message = "redo"
        return True

    # -- notes ---------------------------------------------------------

    def note_at(self, track, step):
        """The note that starts on `step`, if one does."""
        for note in track.get("notes") or ():
            if note[0] == step:
                return note
        return None

    def note_over(self, track, step):
        """The note sounding on `step`, whether it starts there or holds."""
        found = self.note_at(track, step)
        if found is not None:
            return found
        for note in track.get("notes") or ():
            if note[0] <= step < note[0] + note[1]:
                return note
        return None

    def toggle(self, track_index, step):
        """A click on a cell: write a note there, or take the one away."""
        track = sfx.track_of(self.doc, track_index)
        if track is None:
            return False
        self._push_undo()
        note = self.note_at(track, step)
        if note is not None:
            track["notes"].remove(note)
            self._touch(f"removed {sfx.note_name(note[2] + self._oct(track))}")
        else:
            track["notes"].append([int(step), 1, 72, 1.0])
            track["notes"].sort(key=lambda n: (n[0], n[2]))
            self._touch(f"note {sfx.note_name(72 + self._oct(track))} at "
                        f"step {step}")
        self.track = track_index
        return True

    def remove(self, track_index, step):
        track = sfx.track_of(self.doc, track_index)
        note = self.note_over(track, step) if track is not None else None
        if note is None:
            return False
        self._push_undo()
        track["notes"].remove(note)
        self._touch("note removed")
        return True

    def shift(self, track_index, step, delta):
        """Wheel over a cell: move its note by `delta` semitones."""
        track = sfx.track_of(self.doc, track_index)
        note = self.note_over(track, step) if track is not None else None
        if note is None:
            return False
        self._push_undo()
        note[2] = max(0, min(127, int(note[2]) + int(delta)))
        self._touch(f"{sfx.note_name(note[2] + self._oct(track))} "
                    f"(midi {note[2]})")
        return True

    def stretch(self, track_index, step, delta):
        """Ctrl+wheel over a cell: lengthen or shorten its note."""
        track = sfx.track_of(self.doc, track_index)
        note = self.note_over(track, step) if track is not None else None
        if note is None:
            return False
        steps = int(self.doc.get("steps") or sfx.STEPS)
        self._push_undo()
        note[1] = max(1, min(steps - note[0], int(note[1]) + int(delta)))
        self._touch(f"length {note[1]}")
        return True

    @staticmethod
    def _oct(track):
        return int(track.get("octave") or 0) * 12

    # -- tracks and buttons --------------------------------------------

    def add_track(self):
        if self.doc is None:
            return False
        self._push_undo()
        waves = sfx.WAVES
        used = len(self.doc["tracks"])
        self.doc["tracks"].append(dict(
            sfx.TRACK, name=f"track {used + 1}", wave=waves[used % len(waves)],
            gain=0.4, notes=[]))
        self.track = len(self.doc["tracks"]) - 1
        self._touch(f"added {self.doc['tracks'][self.track]['name']}")
        return True

    def remove_track(self):
        if self.doc is None or len(self.doc["tracks"]) < 2:
            self.message = "a project keeps at least one track"
            return False
        self._push_undo()
        gone = self.doc["tracks"].pop(self.track)
        self.track = max(0, min(len(self.doc["tracks"]) - 1, self.track))
        self._touch(f"removed {gone.get('name')}")
        return True

    def bump(self, key, delta, low, high):
        if self.doc is None:
            return False
        self._push_undo()
        value = int(self.doc.get(key) or 0) + delta
        self.doc[key] = max(low, min(high, value))
        self._touch(f"{key} {self.doc[key]}")
        return True

    def cycle_steps(self):
        if self.doc is None:
            return False
        current = int(self.doc.get("steps") or sfx.STEPS)
        try:
            at = STEP_CHOICES.index(current)
        except ValueError:
            at = 0
        self._push_undo()
        steps = STEP_CHOICES[(at + 1) % len(STEP_CHOICES)]
        self.doc["steps"] = steps
        for track in self.doc["tracks"]:
            # a note reaching past the new end is cut to the grid
            for note in track["notes"]:
                note[0] = min(note[0], steps - 1)
                note[1] = max(1, min(note[1], steps - note[0]))
        self._touch(f"{steps} steps")
        return True

    def open_waves(self):
        """Open the tone-shape list under the Wave button."""
        track = self.current_track()
        anchor = self._wave_rect
        if track is None or anchor is None:
            return False
        self.picks = widgets.Choices(sfx.WAVES, anchor, self.area).filter("")
        return True

    def pick_wave(self, word):
        """Take a tone shape from the open list."""
        self.picks = None
        track = self.current_track()
        if track is None or word not in sfx.WAVES:
            return False
        self._push_undo()
        track["wave"] = str(word)
        self._touch(f"{track.get('name')}: {track['wave']}")
        return True

    def toggle_bits(self):
        if self.doc is None:
            return False
        self._push_undo()
        self.doc["bits"] = 8 if int(self.doc.get("bits") or 16) == 16 else 16
        self._touch(f"{self.doc['bits']}-bit tones")
        return True

    def toggle_loop(self):
        if self.doc is None:
            return False
        self._push_undo()
        self.doc["loop"] = not bool(self.doc.get("loop"))
        self._touch(f"loop {'on' if self.doc['loop'] else 'off'}")
        return True

    def nudge(self, key, delta, low, high):
        """Move a track's own number by `delta`, kept inside its range."""
        track = self.current_track()
        if track is None:
            return False
        self._push_undo()
        track[key] = round(max(low, min(high, float(track.get(key) or 0.0)
                                       + delta)), 3)
        self._touch(f"{track.get('name')} {key} {track[key]:g}")
        return True

    def bump_track(self, key, delta, low, high):
        """Move one of a track's whole numbers, kept inside its range."""
        track = self.current_track()
        if track is None:
            return False
        self._push_undo()
        value = int(track.get(key) or 0) + int(delta)
        track[key] = max(low, min(high, value))
        self._touch(f"{track.get('name')} {key} {track[key]:+d}"
                    if key == "octave" else
                    f"{track.get('name')} {key} {track[key]}")
        return True

    def cycle_duck(self):
        """Step the sidechain depth: 0, 25, 50, 75, 100 per cent."""
        track = self.current_track()
        if track is None:
            return False
        steps = (0.0, 0.25, 0.5, 0.75, 1.0)
        if len(self.doc["tracks"]) < 2 and not track.get("duck"):
            self.message = "ducking needs a second track to follow"
            self.app.log("sfx: ducking needs a second track to follow",
                         "warn")
            return False
        self._push_undo()
        deep = float(track.get("duck") or 0.0)
        at = min(range(len(steps)), key=lambda i: abs(steps[i] - deep))
        track["duck"] = steps[(at + 1) % len(steps)]
        if track["duck"] and int(track.get("duck_by") or 0) == self.track:
            track["duck_by"] = 0 if self.track != 0 else 1
        if track["duck"]:
            self._touch(f"{track.get('name')} ducks "
                        f"{track['duck'] * 100:.0f}% under track "
                        f"{int(track.get('duck_by') or 0) + 1}")
        else:
            self._touch(f"{track.get('name')} no longer ducks")
        return True

    def cycle_duck_source(self):
        """Pick which other track this one's sidechain follows."""
        track = self.current_track()
        if track is None or len(self.doc["tracks"]) < 2:
            self.message = "ducking needs a second track to follow"
            return False
        self._push_undo()
        count = len(self.doc["tracks"])
        at = int(track.get("duck_by") or 0)
        nxt = (at + 1) % count
        if nxt == self.track:
            nxt = (nxt + 1) % count
        track["duck_by"] = nxt
        self._touch(f"{track.get('name')} follows track {nxt + 1}")
        return True

    def cycle_duck_release(self):
        """Pick how fast the sidechain recovers."""
        track = self.current_track()
        if track is None:
            return False
        steps = (0.05, 0.15, 0.3, 0.6)
        self._push_undo()
        deep = float(track.get("duck_release") or 0.15)
        at = min(range(len(steps)), key=lambda i: abs(steps[i] - deep))
        track["duck_release"] = steps[(at + 1) % len(steps)]
        self._touch(f"release {track['duck_release']:g}s")
        return True

    def cycle_rate(self):
        """Step the sample rate the pattern renders at."""
        if self.doc is None:
            return False
        self._push_undo()
        rates = sfx.RATES
        now = int(self.doc.get("rate") or sfx.RATES[2])
        at = min(range(len(rates)), key=lambda i: abs(rates[i] - now))
        self.doc["rate"] = rates[(at + 1) % len(rates)]
        self._touch(f"{self.doc['rate']} Hz")
        return True

    def toggle_mute(self):
        track = self.current_track()
        if track is None:
            return False
        self._push_undo()
        track["mute"] = not bool(track.get("mute"))
        self._touch(f"{track.get('name')} "
                    f"{'muted' if track['mute'] else 'unmuted'}")
        return True

    def prompt_sample(self):
        """Ask for an audio file to mix under the grid."""
        if self.doc is None:
            self.app.log("sfx: open or make a sound project first", "warn")
            return
        self.app.dialog_kind = "sfx_sample"
        self.app.dialog = widgets.PromptDialog(
            "Import a Sample", "Audio file path", "",
            hint="wav, ogg, mp3 or flac: the file is copied into audio/ as a "
                 "wav and mixed under the tracks. Click the ruler to choose "
                 "where, then the sample row, to place it.", width=470)

    def add_sample(self, raw):
        """Mix an external file in, copied into the project's audio."""
        if self.doc is None:
            return False
        source = Path(str(raw or "").strip().strip('"')).expanduser()
        if not source.is_file():
            self.app.log(f"no such file: {source}", "error")
            return False
        if source.suffix.lower() not in sfx.IMPORTS:
            # the engine plays wav; the others arrive only through a decoder
            self.app.log(f"{source.name}: import wav, ogg, mp3 or flac",
                         "warn")
            return False
        folder = Path(self._audio_dir() or "")
        if not str(folder):
            return False
        try:
            target = sfx.import_audio(source, folder)
        except (OSError, ValueError) as exc:
            self.app.log(f"cannot copy {source.name}: {exc}", "error")
            return False
        self._push_undo()
        self.doc["samples"].append({"file": target.name,
                                    "at": self.step * sfx.step_seconds(
                                        self.doc),
                                    "gain": 0.9, "pitch": 1.0})
        self._touch(f"sample {target.name}")
        self.app.log(f"sfx: {target.name} copied into audio/ and mixed under "
                     "the tracks", "ok")
        self.app.refresh_tree()
        return True

    def place_sample(self, index):
        """A click on a sample row moves it to the chosen step."""
        samples = (self.doc or {}).get("samples") or []
        if not 0 <= index < len(samples):
            return False
        self._push_undo()
        samples[index]["at"] = self.step * sfx.step_seconds(self.doc)
        self._touch(f"{samples[index]['file']} at step {self.step}")
        return True

    def remove_sample(self, index):
        samples = (self.doc or {}).get("samples") or []
        if not 0 <= index < len(samples):
            return False
        self._push_undo()
        gone = samples.pop(index)
        self._touch(f"dropped {gone.get('file')}")
        return True

    # -- the preview ---------------------------------------------------

    def is_playing(self):
        if self._sound is None or self.started is None:
            return False
        try:
            live = self._sound.get_num_channels() > 0
        except pygame.error:
            live = False
        if not live:
            self.started = None
        return live

    def play(self):
        """Render the document and play it through the mixer."""
        self.stop()
        if self.doc is None:
            return False
        try:
            snd = sfx.sound(self.doc, audio_dir=self._audio_dir(),
                            settings=self.app.audio.settings)
        except (OSError, ValueError, pygame.error) as exc:
            self.app.log(f"sfx: cannot play it: {exc}", "error")
            return False
        if snd is None:
            return False
        self._sound = snd
        channel = snd.play(loops=-1 if self.doc.get("loop") else 0)
        if channel is not None:
            channel.set_volume(PREVIEW_VOLUME)
        self.started = time.time()
        return True

    def toggle_play(self):
        """Start the preview, or stop the one running."""
        if self.is_playing():
            self.stop()
            return True
        return self.play()

    def stop(self):
        if self._sound is not None:
            try:
                self._sound.stop()
            except pygame.error:
                pass
        self._sound = None
        self.started = None

    def playhead(self):
        """The step the preview has reached, or None when it is stopped."""
        if not self.is_playing() or self.doc is None or self.started is None:
            return None
        step = sfx.step_seconds(self.doc)
        if step <= 0:
            return None
        steps = int(self.doc.get("steps") or sfx.STEPS)
        at = int((time.time() - self.started) / step)
        return at % steps if self.doc.get("loop") else min(steps - 1, at)

    # -- events --------------------------------------------------------

    def handle_event(self, e):
        if self.picks is not None:
            got = self._picks_event(e)
            if got is not None:
                return got
        if e.type == pygame.MOUSEWHEEL:
            hit = self._cell_at(pygame.mouse.get_pos())
            if hit is None:
                return False
            mods = pygame.key.get_mods()
            if mods & pygame.KMOD_CTRL:
                return self.stretch(hit[0], hit[1], 1 if e.y > 0 else -1)
            return self.shift(hit[0], hit[1],
                              (12 if mods & pygame.KMOD_SHIFT else e.y))
        if e.type == pygame.KEYDOWN:
            return self._key(e)
        if e.type == pygame.MOUSEBUTTONDOWN:
            pos = e.pos
            for button in self.buttons:
                if button["rect"].collidepoint(pos):
                    self._act(button["action"], e.button, e.mod)
                    return True
            if e.button == 3:
                hit = self._cell_at(pos)
                if hit is not None:
                    return self.remove(*hit)
                row = self._sample_at(pos)
                if row is not None:
                    return self.remove_sample(row)
                return False
            if e.button != 1:
                return False
            for index, rect in self.tracks:
                if rect.collidepoint(pos):
                    self.track = index
                    self.message = (sfx.track_of(self.doc, index) or {}).get(
                        "name", "")
                    return True
            for path, rect in self.file_rows:
                if rect.collidepoint(pos):
                    return self.open(path)
            row = self._sample_at(pos)
            if row is not None:
                return self.place_sample(row)
            if self.ruler.collidepoint(pos) and self.cell > 0:
                step = (pos[0] - self.ruler.x) // self.cell
                steps = int((self.doc or {}).get("steps") or sfx.STEPS)
                self.step = max(0, min(steps - 1, int(step)))
                self.message = f"step {self.step}"
                return True
            hit = self._cell_at(pos)
            if hit is not None:
                return self.toggle(*hit)
            return False
        return False

    def _key(self, e):
        ctrl = bool(e.mod & pygame.KMOD_CTRL)
        shift = bool(e.mod & pygame.KMOD_SHIFT)
        if ctrl and shift and e.key in (pygame.K_z, pygame.K_y):
            return self.redo_step()
        if ctrl and e.key == pygame.K_z:
            return self.undo_step()
        if ctrl and e.key == pygame.K_y:
            return self.redo_step()
        if e.key == pygame.K_SPACE:
            return self.toggle_play()
        if self.doc is None:
            return False
        steps = int(self.doc.get("steps") or sfx.STEPS)
        if e.key == pygame.K_LEFT:
            self.step = (self.step - 1) % steps
            return True
        if e.key == pygame.K_RIGHT:
            self.step = (self.step + 1) % steps
            return True
        if e.key == pygame.K_UP:
            self.track = max(0, self.track - 1)
            return True
        if e.key == pygame.K_DOWN:
            self.track = min(len(self.doc["tracks"]) - 1, self.track + 1)
            return True
        if e.key in (pygame.K_DELETE, pygame.K_BACKSPACE):
            return self.remove(self.track, self.step)
        if e.key == pygame.K_RETURN:
            return self.toggle(self.track, self.step)
        if ctrl and e.key == pygame.K_m:
            return self.toggle_mute()
        return False

    def _cell_at(self, pos):
        for track, step, rect in self.cells:
            if rect.collidepoint(pos):
                return track, step
        return None

    def _picks_event(self, e):
        """The open tone list takes its own rows; anything else closes it."""
        picks = self.picks
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                self.picks = None
                return True
            if e.key in (pygame.K_UP, pygame.K_DOWN):
                picks.step(-1 if e.key == pygame.K_UP else 1)
                return True
            if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return self.pick_wave(picks.current())
            return None
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if picks.holds(e.pos):
                word = picks.click(e.pos)
                return True if word is None else self.pick_wave(word)
            self.picks = None
            return None
        if e.type == pygame.MOUSEBUTTONDOWN:
            self.picks = None
            return None
        return None

    def _sample_at(self, pos):
        for index, rect in self.sample_rows:
            if rect.collidepoint(pos):
                return index
        return None

    def _act(self, action, button=1, mods=0):
        kind = action[0]
        if kind == "toggle":
            return self.toggle_play()
        if kind == "new-sfx":
            self.prompt_new("sfx")
            return True
        if kind == "new-music":
            self.prompt_new("music")
            return True
        if kind == "save":
            return self.save()
        if kind == "import":
            self.prompt_sample()
            return True
        if kind == "bpm-":
            return self.bump("bpm", 5 if button == 3 else -5,
                             sfx.MIN_BPM, sfx.MAX_BPM)
        if kind == "bits":
            return self.toggle_bits()
        if kind == "loop":
            return self.toggle_loop()
        if kind == "wave-menu":
            return self.open_waves()
        if kind == "gain+":
            step = 0.15 if mods & pygame.KMOD_CTRL else 0.05
            return self.nudge("gain", -step if button == 3 else step,
                              0.0, 1.5)
        if kind == "oct+":
            return self.bump_track("octave", -1 if button == 3 else 1,
                                   -4, 4)
        if kind == "duck":
            return self.cycle_duck()
        if kind == "duckby":
            return self.cycle_duck_source()
        if kind == "duckrel":
            return self.cycle_duck_release()
        if kind == "rate":
            return self.cycle_rate()
        if kind == "steps":
            return self.cycle_steps()
        if kind == "track+":
            return self.add_track()
        if kind == "track-":
            return self.remove_track()
        if kind == "mute":
            return self.toggle_mute()
        return False

    # -- painting ------------------------------------------------------

    def draw(self, surface, rect):
        self._layout(pygame.Rect(rect))
        pygame.draw.rect(surface, xp.PANEL, self.area)
        self._draw_toolbar(surface)
        self._draw_list(surface)
        if self.doc is None:
            self._draw_empty(surface)
            return
        self._draw_ruler(surface)
        self._draw_tracks(surface)
        self._draw_samples(surface)
        if self.hover_tip:
            xp.tooltip(surface, self.hover_pos, [self.hover_tip],
                       self.app.fonts["small"])

    def _layout(self, rect):
        self.area = rect
        left = min(LIST_W, max(120, rect.width // 4))
        self.list_rect = pygame.Rect(rect.x, rect.y, left, rect.height)
        self.list_head = pygame.Rect(self.list_rect.x, self.list_rect.y,
                                     left, HEAD_H)
        self.list_body = pygame.Rect(self.list_rect.x, self.list_head.bottom,
                                     left, rect.height - HEAD_H)
        right = pygame.Rect(self.list_rect.right + 6, rect.y + 6,
                            max(40, rect.right - self.list_rect.right - 12),
                            rect.height - 12)
        # the buttons wrap onto a second row before any of them is dropped
        bar_rows = self._toolbar_rows(right.width, self.app.fonts["small"])
        self.bar = pygame.Rect(right.x, right.y, right.width,
                               BAR_H * bar_rows + 4 * (bar_rows - 1))
        body = pygame.Rect(right.x, self.bar.bottom + 6, right.width,
                           max(20, right.bottom - self.bar.bottom - 6))
        rows = max(1, min(4, len((self.doc or {}).get("samples") or ())))
        strip = SAMPLE_H * rows + 16 if self.doc is not None else 0
        self.samples_rect = pygame.Rect(body.x, body.bottom - strip,
                                        body.width, strip)
        self.ruler = pygame.Rect(body.x + NAME_W, body.y,
                                 max(0, body.width - NAME_W), RULER_H)
        self.grid_rect = pygame.Rect(body.x, self.ruler.bottom, body.width,
                                     max(0, self.samples_rect.y -
                                         self.ruler.bottom - 2))
        steps = int((self.doc or {}).get("steps") or sfx.STEPS)
        room = max(32, self.ruler.width - 6)
        self.cell = max(CELL_MIN, min(CELL_MAX, room // max(1, steps)))

    def _toolbar_items(self):
        """(label, action, active, tip) for every button, in order."""
        doc = self.doc or {}
        track = self.current_track() or {}
        playing = self.is_playing()
        duck = float(track.get("duck") or 0.0)
        release = float(track.get("duck_release") or 0.15)
        source = int(track.get("duck_by") or 0) + 1
        return [
            ("Stop" if playing else "Play", ("toggle",), playing,
             "Render the pattern and play it (space)"),
            ("New SFX", ("new-sfx",), False,
             "Make a short, one-shot sound project in audio/"),
            ("New Music", ("new-music",), False,
             "Make a looping pattern in audio/"),
            ("Save", ("save",), False,
             "Flatten to a sound file and delete the project file"),
            ("Import", ("import",), False,
             "Mix an imported wav, ogg, mp3 or flac under the tracks"),
            (f"BPM {doc.get('bpm', sfx.DEFAULT_BPM)}", ("bpm-",), False,
             "Left-click slows the pattern, right-click speeds it up"),
            (f"{doc.get('steps', sfx.STEPS)} steps", ("steps",), False,
             "Pattern length; click for the next size"),
            (f"{doc.get('bits', 16)}-bit", ("bits",), False,
             "Chip depth: 8-bit is crunchier than 16-bit"),
            (f"Loop {'on' if doc.get('loop') else 'off'}", ("loop",),
             bool(doc.get("loop")), "Repeat the pattern when it is played"),
            (f"Wave {track.get('wave') or '-'}", ("wave-menu",), False,
             "Choose this track's tone shape"),
            (f"Gain {float(track.get('gain') or 0.0) * 100:.0f}%",
             ("gain+",), False,
             "Left-click louder, right-click quieter (Ctrl for a big step)"),
            (f"Oct {int(track.get('octave') or 0):+d}", ("oct+",), False,
             "Left-click up an octave, right-click down"),
            (f"Duck {duck * 100:.0f}%", ("duck",), duck > 0,
             "Sidechain depth: click to cycle 0, 25, 50, 75, 100%"),
            (f"By {source}", ("duckby",), False,
             "Which track this one ducks under"),
            (f"Rel {release:g}s", ("duckrel",), False,
             "How fast the sidechain recovers"),
            (f"{doc.get('rate', sfx.RATES[2])} Hz", ("rate",), False,
             "Sample rate the pattern is rendered at"),
            ("+ Track", ("track+",), False, "Add a tone track"),
            ("- Track", ("track-",), False, "Remove the selected track"),
            ("Mute", ("mute",), bool(track.get("mute")),
             "Silence the selected track"),
        ]

    def _toolbar_rows(self, width, font):
        """How many rows the buttons need, so the grid sits below them."""
        rows, x = 1, 0
        for label, _action, _active, _tip in self._toolbar_items():
            span = font.size(label)[0] + 14 + 4
            if x and x + span > width:
                rows += 1
                x = 0
            x += span
        return rows

    def _draw_toolbar(self, surface):
        self.buttons = []
        self.hover_tip = None
        self.hover_pos = pygame.mouse.get_pos()
        self._wave_rect = None
        mouse = self.hover_pos
        font = self.app.fonts["small"]
        x, y = self.bar.x, self.bar.y
        for label, action, active, tip in self._toolbar_items():
            width = font.size(label)[0] + 14
            if x > self.bar.x and x + width > self.bar.right:
                x = self.bar.x
                y += BAR_H + 4
            box = pygame.Rect(x, y, width, BAR_H)
            xp.button(surface, box, label, font, pressed=active,
                      hovered=box.collidepoint(mouse))
            self.buttons.append({"action": action, "rect": box})
            if action[0] == "wave-menu":
                self._wave_rect = box
            if box.collidepoint(mouse):
                self.hover_tip = tip
            x += width + 4
        if self.picks is not None:
            self.picks.draw(surface, font)

    def _draw_list(self, surface):
        files = self.project.sfx_files() if self.project is not None else []
        widgets.header(surface, self.list_head, "Sound projects",
                       self.app.fonts["small"], right=f"{len(files)}")
        pygame.draw.rect(surface, xp.FIELD, self.list_body)
        xp.sunken(surface, self.list_body)
        inner = self.list_body.inflate(-2, -2)
        self.file_rows = []
        if not files:
            img = widgets.cached_text(self.app.fonts["small"],
                                      "no sound projects", xp.TEXT_MUTED)
            surface.blit(img, (inner.x + 6, inner.y + 6))
            img = widgets.cached_text(self.app.fonts["small"],
                                      "New SFX makes one", xp.TEXT_MUTED)
            surface.blit(img, (inner.x + 6, inner.y + 22))
            return
        row_h = 32
        page = max(1, inner.height // row_h)
        self.scroll = max(0, min(self.scroll, max(0, len(files) - page)))
        old = surface.get_clip()
        surface.set_clip(inner)
        y = inner.y + 1 - self.scroll * row_h
        for path in files[self.scroll:self.scroll + page + 1]:
            row = pygame.Rect(inner.x, y, inner.width - 2, row_h - 2)
            y += row_h
            self.file_rows.append((path, row))
            selected = self.path is not None and path == self.path
            if selected:
                surface.fill(xp.SELECTION, row)
            elif row.collidepoint(pygame.mouse.get_pos()):
                surface.fill(xp.BTN_HOVER_BG, row)
            color = xp.SELECT_TEXT if selected else xp.TEXT
            widgets.file_icon(surface, (row.x + 4, row.y + 9),
                              sfx.SFX_EXT, self.app.fonts["small"], 13)
            name = widgets.elide(self.app.fonts["small"], path.stem,
                                 row.width - 40)
            img = widgets.cached_text(self.app.fonts["small"], name, color)
            surface.blit(img, (row.x + 22, row.y + 3))
            length = self._project_length(path)
            img = widgets.cached_text(
                self.app.fonts["small"],
                f"{length:.2f}s" if length else "-",
                xp.SELECT_SUBTEXT if selected else xp.TEXT_MUTED)
            surface.blit(img, (row.x + 22, row.y + 16))
        surface.set_clip(old)

    def _project_length(self, path):
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            return 0.0
        key = (str(path), mtime)
        if key in self._lengths:
            return self._lengths[key]
        try:
            seconds = sfx.length(sfx.load(path))
        except (OSError, ValueError):
            seconds = 0.0
        if len(self._lengths) > 64:
            self._lengths.clear()
        self._lengths[key] = seconds
        return seconds

    def _draw_empty(self, surface):
        font = self.app.fonts["normal"]
        small = self.app.fonts["small"]
        cx = self.grid_rect.centerx if self.grid_rect.width else \
            self.area.centerx
        cy = self.bar.bottom + 40
        img = widgets.cached_text(font, "no sound project open", xp.TEXT_MUTED)
        surface.blit(img, (cx - img.get_width() // 2, cy))
        lines = [
            "New SFX makes a one-shot pattern; New Music makes a looping one.",
            "Click a cell to place a note, wheel it to change the pitch,",
            "ctrl+wheel to change its length, and right-click to remove it.",
            "Save flattens the pattern into a wav and deletes the project.",
        ]
        y = cy + 24
        for line in lines:
            img = widgets.cached_text(small, line, xp.TEXT_MUTED)
            surface.blit(img, (cx - img.get_width() // 2, y))
            y += small.get_height() + 3

    def _draw_ruler(self, surface):
        steps = int((self.doc or {}).get("steps") or sfx.STEPS)
        surface.fill(xp.FACE, (self.ruler.x, self.ruler.y, self.ruler.width,
                               RULER_H))
        font = self.app.fonts["small"]
        for step in range(steps):
            x = self.ruler.x + step * self.cell
            if x >= self.ruler.right:
                break
            beat = step % 4 == 0
            if beat:
                pygame.draw.line(surface, xp.DK_SHADOW, (x, self.ruler.y + 2),
                                 (x, self.ruler.bottom - 1))
            if self.cell >= 14 or beat:
                label = str(step // 4 + 1) if beat else ""
                if label:
                    img = widgets.cached_text(font, label, xp.TEXT_MUTED)
                    if img is not None:
                        surface.blit(img, (x + 2, self.ruler.y + 1))
        # the chosen step, where a placed sample lands
        x = self.ruler.x + self.step * self.cell
        pygame.draw.rect(surface, xp.SELECTION,
                         (x, self.ruler.bottom - 3, max(2, self.cell - 1), 3))

    def _draw_tracks(self, surface):
        self.cells = []
        self.tracks = []
        doc = self.doc
        steps = int(doc.get("steps") or sfx.STEPS)
        font = self.app.fonts["small"]
        mouse = pygame.mouse.get_pos()
        head = self.playhead()
        area = self.grid_rect
        surface.fill(xp.FIELD, area)
        xp.sunken(surface, area)
        y = self.ruler.bottom + 2
        for index, track in enumerate(doc.get("tracks") or ()):
            if y + ROW_H > area.bottom + 2:
                break
            row = pygame.Rect(area.x, y, area.width, ROW_H)
            selected = index == self.track
            if selected:
                surface.fill(xp.FIELD_ALT, row)
            name_cell = pygame.Rect(row.x + 2, row.y, NAME_W - 6, ROW_H - 2)
            self.tracks.append((index, name_cell))
            self._draw_track_name(surface, name_cell, track, selected, font)
            for step in range(steps):
                x = self.ruler.x + step * self.cell
                if x >= area.right:
                    break
                cell = pygame.Rect(x, row.y + 2, max(3, self.cell - 1),
                                   ROW_H - 6)
                self.cells.append((index, step, cell))
                beat = step % 4 == 0
                surface.fill(xp.TRACK_BG if beat else xp.SCROLL_TROUGH, cell)
                note = self.note_at(track, step)
                held = note is None and self.note_over(track, step) is not None
                colour = WAVE_COLORS.get(track.get("wave"), xp.TRACK_FILL)
                if track.get("mute"):
                    colour = xp.SHADOW
                if note is not None:
                    body = pygame.Rect(x, row.y + 2,
                                       max(3, self.cell * note[1] - 1),
                                       ROW_H - 6)
                    pygame.draw.rect(surface, colour, body, border_radius=2)
                    if body.width >= 26:
                        img = widgets.cached_text(
                            font, sfx.note_name(note[2] + self._oct(track)),
                            xp.SELECT_TEXT)
                        if img is not None:
                            surface.blit(img, (body.x + 3,
                                               body.centery -
                                               img.get_height() // 2))
                elif held:
                    surface.fill(xp.SELECT_BORDER, cell)
                if head == step:
                    pygame.draw.rect(surface, xp.LINK, cell, 1)
                if cell.collidepoint(mouse) and note is not None:
                    self.hover_tip = (f"{sfx.note_name(note[2] +
                                                       self._oct(track))} "
                                      f"step {step}, {note[1]} long")
            y += ROW_H

    def _draw_track_name(self, surface, cell, track, selected, font):
        pygame.draw.rect(surface, xp.SELECTION if selected else xp.FACE, cell)
        colour = WAVE_COLORS.get(track.get("wave"), xp.TRACK_FILL)
        chip = pygame.Rect(cell.x + 4, cell.centery - 4, 8, 8)
        pygame.draw.rect(surface, colour if not track.get("mute")
                         else xp.SHADOW, chip)
        pygame.draw.rect(surface, xp.DK_SHADOW, chip, 1)
        name = widgets.elide(font, str(track.get("name") or "track"),
                             cell.width - 18)
        img = widgets.cached_text(font, name,
                                  xp.SELECT_TEXT if selected else xp.TEXT)
        if img is not None:
            surface.blit(img, (chip.right + 4,
                               cell.centery - img.get_height() // 2))
        if track.get("duck"):
            tag = widgets.cached_text(font, "duck", xp.TEXT_MUTED)
            if tag is not None and tag.get_width() < cell.width - 8:
                surface.blit(tag, (cell.right - tag.get_width() - 4,
                                   cell.bottom - tag.get_height() - 1))

    def _draw_samples(self, surface):
        self.sample_rows = []
        if self.samples_rect.height <= 0:
            return
        font = self.app.fonts["small"]
        samples = self.doc.get("samples") or []
        x = self.samples_rect.x
        y = self.samples_rect.y
        caption = ("Samples: click a row to place it at the chosen step, "
                   "right-click to drop it" if samples else
                   "Samples: Import mixes a .wav under the tracks")
        img = widgets.cached_text(font, caption, xp.TEXT_MUTED)
        surface.blit(img, (x, y))
        y += SAMPLE_H
        step = sfx.step_seconds(self.doc)
        for index, sample in enumerate(samples[:4]):
            row = pygame.Rect(x, y, self.samples_rect.width, SAMPLE_H)
            self.sample_rows.append((index, row))
            if row.collidepoint(pygame.mouse.get_pos()):
                surface.fill(xp.BTN_HOVER_BG, row)
            widgets.file_icon(surface, (row.x, row.y + 2), ".wav", font, 13)
            at = int(round(float(sample.get("at") or 0.0) /
                           max(step, 1e-6)))
            gain = float(sample.get("gain") or 0.0)
            pitch = float(sample.get("pitch") or 1.0)
            text = (f"{sample.get('file')}  step {at}  x{gain:.0f}%  "
                    f"pitch {pitch:.2f}")
            img = widgets.cached_text(font, widgets.elide(
                font, text, row.width - 24), xp.TEXT)
            if img is not None:
                surface.blit(img, (row.x + 18,
                                   row.y + (SAMPLE_H -
                                            img.get_height()) // 2))
            y += SAMPLE_H

    # -- inspector -----------------------------------------------------

    def info(self):
        if self.doc is None:
            return [("Project", "none open"),
                    ("Hint", "New SFX or New Music makes one")]
        doc = self.doc
        track = self.current_track() or {}
        duck = float(track.get("duck") or 0.0)
        rows = [
            ("Project", self.path.name if self.path else "-"),
            ("Kind", str(doc.get("kind"))),
            ("Tempo", f"{doc.get('bpm')} bpm"),
            ("Steps", f"{doc.get('steps')} ({sfx.length(doc):.2f}s)"),
            ("Tones", f"{doc.get('bits')}-bit"),
            ("Tracks", str(len(doc.get('tracks') or ()))),
            ("Notes", str(sfx.note_count(doc))),
            ("Samples", str(len(doc.get('samples') or ()))),
            ("Track", f"{self.track + 1}: {track.get('name', '-')}"),
            ("Wave", str(track.get("wave", "-"))),
            ("Gain", f"{float(track.get('gain') or 0.0) * 100:.0f}%"),
            ("Duck", f"{duck * 100:.0f}%" if duck else "off"),
            ("Mute", "on" if track.get("mute") else "off"),
            ("Loop", "on" if doc.get("loop") else "off"),
            ("Playing", "yes" if self.is_playing() else "no"),
            ("Save", "wav, then the project goes"),
            ("State", "unsaved edits" if self.dirty else "written"),
        ]
        return rows
