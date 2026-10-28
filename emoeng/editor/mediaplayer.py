"""The Audio tab: a player for the project's audio."""

from __future__ import annotations

import array
import sys
import time
import wave
from pathlib import Path

import pygame

from ..engine import xp
from . import widgets

AUDIO_EXT = (".wav", ".ogg", ".mp3", ".flac")
WAVE_CACHE = {}
PEAK_CACHE = {}
DURATION_CACHE = {}


def wav_info(path):
    """Duration, rate and channels of a wav, or None."""
    try:
        with wave.open(str(path), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
            return {
                "frames": frames,
                "rate": rate,
                "channels": w.getnchannels(),
                "width": w.getsampwidth(),
                "duration": frames / float(rate or 1),
            }
    except (wave.Error, OSError, EOFError):
        return None


def wav_peaks(path, buckets=220):
    """Bucketed peak amplitudes in 0..1, cached by file mtime."""
    path = Path(path)
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return None
    key = (str(path), mtime, buckets)
    if key in PEAK_CACHE:
        return PEAK_CACHE[key]
    info = wav_info(path)
    peaks = None
    if info is not None and info["width"] == 2 and info["frames"]:
        try:
            with wave.open(str(path), "rb") as w:
                raw = w.readframes(info["frames"])
            samples = array.array("h")
            samples.frombytes(raw)
            if sys.byteorder != "little":
                samples.byteswap()
            step = max(1, len(samples) // buckets)
            peaks = []
            for i in range(buckets):
                chunk = samples[i * step:(i + 1) * step]
                top = max((abs(v) for v in chunk), default=0) / 32768.0
                peaks.append(min(1.0, top ** 0.65))
        except (wave.Error, OSError, EOFError, ValueError):
            peaks = None
    PEAK_CACHE[key] = peaks
    return peaks


def waveform_image(path, size, fg=None, bg=None):
    """Waveform surface rendered for the asset thumbnails."""
    fg = xp.WAVE_FG if fg is None else fg
    bg = xp.WAVE_BG if bg is None else bg
    size = (max(8, int(size[0])), max(8, int(size[1])))
    try:
        mtime = Path(path).stat().st_mtime_ns
    except OSError:
        mtime = 0
    key = (str(path), mtime, size, fg, bg)
    if key in WAVE_CACHE:
        return WAVE_CACHE[key]
    surf = pygame.Surface(size)
    surf.fill(bg)
    cy = size[1] // 2
    pygame.draw.line(surf, xp.WAVE_AXIS, (0, cy), (size[0] - 1, cy))
    peaks = wav_peaks(path, max(16, size[0] - 4))
    if peaks:
        bar = (size[0] - 2) / len(peaks)
        for i, peak in enumerate(peaks):
            h = max(1, int(peak * (cy - 3)))
            x = 1 + int(i * bar)
            pygame.draw.line(surf, fg, (x, cy - h), (x, cy + h))
    WAVE_CACHE[key] = surf
    return surf


def clock(seconds):
    seconds = max(0.0, float(seconds))
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


class MediaPlayer:
    """Plays the project's audio, apart from the scene bank."""

    PLAYLIST_W = 186

    def __init__(self, app):
        self.app = app
        self.fonts = app.fonts
        self.project = None
        self.files = []
        self.index = -1
        self.current = None
        self.duration = 0.0
        self.volume = 0.8
        self.loop = False
        self.playing = False
        self.paused = False
        self.base_ms = 0
        self.started = 0.0
        self.error = None
        self._last_load_error = None
        self.scroll = 0
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.playlist = pygame.Rect(0, 0, 0, 0)
        self.buttons = []
        self.file_rows = []
        self.seek_rect = pygame.Rect(0, 0, 0, 0)
        self.volume_rect = pygame.Rect(0, 0, 0, 0)
        self.seek_drag = False
        self._last_click = (None, 0.0)

    def set_project(self, project):
        self.stop()
        self.project = project
        self.files = list(project.audio_files()) if project else []
        self.scroll = 0
        self.index = -1
        self.current = None
        self.duration = 0.0
        if self.files:
            self.load(self.files[0])
        if project is not None:
            self.app.log(f"audio tab: {len(self.files)} files", "muted")

    def refresh(self):
        if self.project is None:
            return
        keep = self.current
        self.files = list(self.project.audio_files())
        self.index = self._index_of(keep)

    def load(self, path, autoplay=False):
        path = Path(path)
        if path == self.current and not autoplay:
            return
        self.stop()
        self.current = path if path.exists() else None
        self.error = None
        self.duration = self._duration(path) if self.current else 0.0
        self.index = self._index_of(self.current)
        if autoplay and self.current is not None:
            self.play()

    def _duration(self, path):
        path = Path(path)
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = 0
        key = (str(path), mtime)
        if key in DURATION_CACHE:
            return DURATION_CACHE[key]
        length = 0.0
        info = wav_info(path)
        if info is not None:
            length = info["duration"]
        else:
            snd = self.app.audio.sound(path.stem)
            if snd is not None:
                length = float(snd.get_length())
            else:
                try:
                    length = float(pygame.mixer.Sound(str(path)).get_length())
                except pygame.error:
                    length = 0.0
        DURATION_CACHE[key] = length
        return length

    def _index_of(self, path):
        if path is None:
            return -1
        try:
            return self.files.index(Path(path))
        except (ValueError, TypeError):
            return -1

    def play(self):
        if self.current is None:
            return
        if self.playing:
            if self.paused:
                self.resume()
            return
        self._start(self.base_ms / 1000.0)

    def _start(self, offset):
        offset = max(0.0, float(offset))
        try:
            pygame.mixer.music.load(str(self.current))
            pygame.mixer.music.set_volume(self.volume)
            try:
                pygame.mixer.music.play(-1 if self.loop else 0, start=offset)
            except (pygame.error, TypeError):
                pygame.mixer.music.play(-1 if self.loop else 0)
                offset = 0.0
            self.base_ms = int(offset * 1000)
            self.playing = True
            self.paused = False
            self.started = time.time()
            self.error = None
            self._last_load_error = None
        except pygame.error as exc:
            self.playing = False
            self.paused = False
            self.error = str(exc)
            if str(exc) != self._last_load_error:
                self.app.log(f"media player: {exc}", "warn")
                self._last_load_error = str(exc)

    def pause(self):
        if self.playing and not self.paused:
            self.base_ms = int(self.position() * 1000)
            self.paused = True
            try:
                pygame.mixer.music.pause()
            except pygame.error:
                pass

    def resume(self):
        if self.playing and self.paused:
            self.paused = False
            self._start(self.base_ms / 1000.0)

    def stop(self):
        try:
            pygame.mixer.music.stop()
        except pygame.error:
            pass
        self.playing = False
        self.paused = False
        self.base_ms = 0

    def toggle(self):
        if self.playing and not self.paused:
            self.pause()
        elif self.playing and self.paused:
            self.resume()
        else:
            self.play()

    def seek(self, seconds):
        self.base_ms = int(max(0.0, min(self.duration or seconds,
                                        float(seconds))) * 1000)
        if self.playing and not self.paused:
            self._start(self.base_ms / 1000.0)

    def nudge(self, seconds):
        self.seek(self.position() + seconds)

    def step(self, direction):
        if not self.files:
            return
        index = self.index if self.index >= 0 else 0
        index = (index + direction) % len(self.files)
        was_playing = self.playing and not self.paused
        self.load(self.files[index], autoplay=was_playing)

    def set_volume(self, volume):
        self.volume = max(0.0, min(1.0, float(volume)))
        try:
            pygame.mixer.music.set_volume(self.volume)
        except pygame.error:
            pass

    def position(self):
        if not self.playing:
            return self.base_ms / 1000.0
        if self.paused:
            return self.base_ms / 1000.0
        pos = pygame.mixer.music.get_pos()
        if pos is None or pos < 0:
            pos = int((time.time() - self.started) * 1000)
        value = (self.base_ms + pos) / 1000.0
        if self.duration:
            value = min(value, self.duration)
        return value

    def _layout(self, rect):
        self.rect = pygame.Rect(rect)
        head = 22
        self.header = pygame.Rect(rect.x, rect.y, rect.width, head)
        body = pygame.Rect(rect.x, rect.y + head, rect.width,
                           rect.height - head)
        pw = min(self.PLAYLIST_W, max(120, body.width // 3))
        self.playlist = pygame.Rect(body.x, body.y, pw, body.height)
        right = pygame.Rect(self.playlist.right + 8, body.y + 4,
                            body.right - self.playlist.right - 12,
                            body.height - 8)
        self.right = right
        self.info_rect = pygame.Rect(right.x, right.y, right.width, 50)
        self.transport = pygame.Rect(right.x, right.bottom - 32,
                                     right.width, 30)
        self.seek_rect = pygame.Rect(right.x, self.transport.y - 38,
                                     right.width, 24)
        self.wave_rect = pygame.Rect(right.x, self.info_rect.bottom + 2,
                                     right.width,
                                     max(50, self.seek_rect.y -
                                         self.info_rect.bottom - 8))
        self.playlist_head = pygame.Rect(self.playlist.x, self.playlist.y,
                                         self.playlist.width, 20)
        self.playlist_body = pygame.Rect(
            self.playlist.x, self.playlist_head.bottom, self.playlist.width,
            self.playlist.height - self.playlist_head.height)

    def draw(self, surface, rect):
        self._layout(rect)
        pygame.draw.rect(surface, xp.FACE, self.rect)
        right = self.right
        self._poll_end()
        widgets.header(surface, self.header, "Audio", self.fonts["normal"],
                       right=f"{len(self.files)} files",
                       icon="tab-audio-sym")
        self._draw_playlist(surface)
        self._draw_info(surface, right)
        self._draw_wave(surface, self.wave_rect)
        self._draw_seek(surface, self.seek_rect)
        self._draw_transport(surface, self.transport)
        mouse = pygame.mouse.get_pos()
        for action, button in self.buttons:
            if button.collidepoint(mouse):
                tips = {
                    "restart": "Restart this track from the beginning.",
                    "prev": "Select the previous audio file.",
                    "toggle": ("Pause playback." if self.playing and
                               not self.paused else "Start or resume playback."),
                    "stop": "Stop playback and return to the start.",
                    "next": "Select the next audio file.",
                    "loop": "Repeat the selected track.",
                }
                xp.tooltip(surface, mouse, [tips[action]],
                           self.fonts["small"])
                break
        else:
            if self.volume_rect.collidepoint(mouse):
                xp.tooltip(surface, mouse,
                           ["Set the audio preview volume."],
                           self.fonts["small"])

    def _poll_end(self):
        if self.playing and not self.paused and time.time() - self.started > 0.3:
            if not pygame.mixer.music.get_busy():
                self.playing = False
                self.base_ms = 0

    def _draw_playlist(self, surface):
        area = self.playlist
        pygame.draw.rect(surface, xp.FACE, area)
        widgets.header(surface, self.playlist_head, "Project audio",
                       self.fonts["small"])
        body = pygame.Rect(area.x, self.playlist_head.bottom,
                           area.width, area.bottom - self.playlist_head.bottom)
        pygame.draw.rect(surface, xp.FIELD, body)
        xp.sunken(surface, body)
        self.file_rows = []
        if not self.files:
            img = widgets.cached_text(self.fonts["small"],
                                      "no audio files", xp.TEXT_MUTED)
            surface.blit(img, (body.x + 6, body.y + 6))
            return
        row_h = 34
        inner = body.inflate(-2, -2)
        page = max(1, inner.height // row_h)
        max_scroll = max(0, len(self.files) - page)
        self.scroll = max(0, min(self.scroll, max_scroll))
        y = inner.y + 1 - self.scroll * row_h
        for i in range(self.scroll, min(len(self.files), self.scroll + page + 1)):
            path = self.files[i]
            row = pygame.Rect(inner.x, y, inner.width - 10, row_h - 2)
            y += row_h
            self.file_rows.append(row)
            selected = i == self.index
            if selected:
                surface.fill(xp.SELECTION, row)
            elif row.collidepoint(pygame.mouse.get_pos()):
                surface.fill(xp.BTN_HOVER_BG, row)
            color = xp.SELECT_TEXT if selected else xp.TEXT
            widgets.file_icon(surface, (row.x + 5, row.y + 10),
                              path.suffix, self.fonts["small"], 13)
            name = path.stem
            while self.fonts["normal"].size(name)[0] > row.width - 32 and \
                    len(name) > 4:
                name = name[:-2]
            img = widgets.cached_text(self.fonts["normal"], name, color)
            surface.blit(img, (row.x + 23, row.y + 4))
            length = self._duration(path)
            img = widgets.cached_text(self.fonts["small"], clock(length),
                                      xp.SELECT_SUBTEXT if selected
                                      else xp.TEXT_MUTED)
            surface.blit(img, (row.right - img.get_width() - 3, row.y + 4))
        if max_scroll > 0:
            xp.scrollbar(surface, pygame.Rect(body.right - 11, body.y + 2, 9,
                                              body.height - 4),
                         self.scroll / max(1, len(self.files)),
                         page / max(1, len(self.files)))

    def _draw_info(self, surface, rect):
        name = self.current.name if self.current else "no file selected"
        img = widgets.cached_text(self.fonts["big"], name, xp.LINK)
        surface.blit(img, (rect.x, rect.y + 2))
        if self.current is not None:
            sub = self.current.name
            if self.project is not None:
                sub = self.project.relative(self.current)
            img = widgets.cached_text(self.fonts["small"], sub,
                                      xp.TEXT_MUTED)
            surface.blit(img, (rect.x, rect.y + 26))
        right = clock(self.duration) if self.duration else "--:--"
        img = widgets.cached_text(self.fonts["normal"], right, xp.TEXT_MUTED)
        surface.blit(img, (rect.right - img.get_width(), rect.y + 4))

    def _draw_wave(self, surface, rect):
        if rect.height <= 0:
            return
        surface.fill(xp.WAVE_BG, rect)
        xp.sunken(surface, rect)
        peaks = wav_peaks(self.current) if self.current else None
        inner = rect.inflate(-4, -6)
        if not peaks:
            msg = "waveform preview needs a .wav file"
            img = widgets.cached_text(self.fonts["small"], msg,
                                      xp.TEXT_MUTED)
            surface.blit(img, (inner.centerx - img.get_width() // 2,
                               inner.centery - img.get_height() // 2))
            return
        cy = inner.centery
        progress = self.position() / self.duration if self.duration else 0.0
        bar = inner.width / len(peaks)
        played = xp.WAVE_PLAYED
        rest = xp.WAVE_REST
        for i, peak in enumerate(peaks):
            h = max(1, int(peak * (inner.height // 2 - 2)))
            x = inner.x + int(i * bar)
            color = played if (i / len(peaks)) <= progress else rest
            pygame.draw.line(surface, color, (x, cy - h), (x, cy + h))
        pygame.draw.line(surface, xp.WAVE_AXIS, (inner.x, cy),
                         (inner.right, cy))

    def _draw_seek(self, surface, rect):
        track = pygame.Rect(rect.x, rect.y + 4, rect.width, 6)
        pygame.draw.rect(surface, xp.TRACK_BG, track)
        xp.sunken(surface, track)
        frac = (self.position() / self.duration) if self.duration else 0.0
        frac = max(0.0, min(1.0, frac))
        filled = pygame.Rect(track.x + 1, track.y + 1,
                             int((track.width - 2) * frac), track.height - 2)
        if filled.width > 0:
            pygame.draw.rect(surface, xp.TRACK_FILL, filled)
        knob = pygame.Rect(track.x + int(track.width * frac) - 4,
                           rect.y + 1, 8, 12)
        xp.raised(surface, knob)
        img = widgets.cached_text(self.fonts["small"], clock(self.position()),
                                  xp.TEXT_MUTED)
        surface.blit(img, (rect.x, rect.y + 12))
        img = widgets.cached_text(self.fonts["small"], clock(self.duration),
                                  xp.TEXT_MUTED)
        surface.blit(img, (rect.right - img.get_width(), rect.y + 12))

    def _draw_transport(self, surface, rect):
        self.buttons = []
        mouse = pygame.mouse.get_pos()
        x = rect.x
        pausing = self.playing and not self.paused
        # transport is pictures only; glyphs blurred at this size
        for action, art in (("restart", "rewind-sym"),
                            ("prev", "step-backward-sym"),
                            ("toggle", "pause-sym" if pausing
                             else "play-sym"),
                            ("stop", "stop-sym"),
                            ("next", "step-forward-sym")):
            r = pygame.Rect(x, rect.y + 1, 34, rect.height - 2)
            xp.button(surface, r, "", self.fonts["normal"],
                      default=action == "toggle",
                      icon=widgets.icon(art, 16),
                      hovered=r.collidepoint(mouse))
            self.buttons.append((action, r))
            x = r.right + 4
        loop = pygame.Rect(x + 4, rect.y + 2, 66, rect.height - 4)
        xp.button(surface, loop, "Loop", self.fonts["small"],
                  pressed=self.loop,
                  icon=widgets.icon("loop-sym", 14),
                  hovered=loop.collidepoint(mouse))
        self.buttons.append(("loop", loop))
        label = widgets.cached_text(self.fonts["small"], "Vol", xp.TEXT_MUTED)
        vx = loop.right + 12
        surface.blit(label, (vx, rect.centery - label.get_height() // 2))
        track = pygame.Rect(vx + 26, rect.centery - 3,
                            max(40, rect.right - vx - 42), 6)
        self.volume_rect = track
        pygame.draw.rect(surface, xp.TRACK_BG, track)
        xp.sunken(surface, track)
        filled = pygame.Rect(track.x + 1, track.y + 1,
                             int((track.width - 2) * self.volume), 4)
        if filled.width > 0:
            pygame.draw.rect(surface, xp.TRACK_FILL, filled)
        knob = pygame.Rect(track.x + int(track.width * self.volume) - 4,
                           track.y - 4, 8, 14)
        xp.raised(surface, knob)

    def handle_event(self, e):
        pos = getattr(e, "pos", pygame.mouse.get_pos())
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_SPACE:
                self.toggle()
                return True
            if e.key == pygame.K_s:
                self.stop()
                return True
            if e.key == pygame.K_l:
                self.loop = not self.loop
                return True
            if e.key == pygame.K_HOME:
                self.seek(0.0)
                return True
            if e.key == pygame.K_LEFT:
                self.nudge(-2.0)
                return True
            if e.key == pygame.K_RIGHT:
                self.nudge(2.0)
                return True
            return False
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self._seek_rect().collidepoint(pos):
                self._seek_to(pos[0])
                self.seek_drag = True
                return True
            if self.volume_rect.collidepoint(pos):
                self.set_volume((pos[0] - self.volume_rect.x) /
                                max(1, self.volume_rect.width))
                return True
            for action, rect in self.buttons:
                if rect.collidepoint(pos):
                    self._action(action)
                    return True
            for i, row in enumerate(self.file_rows):
                if row.collidepoint(pos):
                    index = i + self.scroll
                    if 0 <= index < len(self.files):
                        now = time.time()
                        again = (self._last_click[0] == index and
                                 now - self._last_click[1] < 0.4)
                        self._last_click = (index, now)
                        self.load(self.files[index], autoplay=again or
                                  self.playing)
                    return True
            return True
        if e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            self.seek_drag = False
            return False
        if e.type == pygame.MOUSEMOTION and self.seek_drag and \
                pygame.mouse.get_pressed()[0]:
            self._seek_to(pos[0])
            return True
        if e.type == pygame.MOUSEWHEEL:
            if self.playlist.collidepoint(pygame.mouse.get_pos()):
                row_h = 34
                page = max(1, self.playlist_body.height // row_h)
                self.scroll = max(0, min(max(0, len(self.files) - page),
                                         self.scroll - e.y * 2))
                return True
        return False

    def _seek_rect(self):
        return pygame.Rect(self.seek_rect.x, self.seek_rect.y,
                           self.seek_rect.width, self.seek_rect.height)

    def _seek_to(self, x):
        frac = (x - self.seek_rect.x) / max(1, self.seek_rect.width)
        self.seek(max(0.0, min(1.0, frac)) * max(self.duration, 0.01))

    def _action(self, action):
        if action == "toggle":
            self.toggle()
        elif action == "stop":
            self.stop()
        elif action == "restart":
            self.seek(0.0)
        elif action == "prev":
            self.step(-1)
        elif action == "next":
            self.step(1)
        elif action == "loop":
            self.loop = not self.loop
            if self.playing and not self.paused:
                self._start(self.position())

    def info(self):
        rows = [
            ("File", self.current.name if self.current else "-"),
            ("Length", clock(self.duration) if self.duration else "-"),
            ("State", "playing" if self.playing and not self.paused else
             "paused" if self.paused else "stopped"),
            ("Position", clock(self.position())),
            ("Loop", "on" if self.loop else "off"),
            ("Volume", f"{self.volume * 100:.0f}%"),
            ("Files", str(len(self.files))),
        ]
        if self.error:
            rows.append(("Error", self.error))
        return rows
