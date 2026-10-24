"""Vertex-based moderngl renderer, tuned for PS2-era looks.

Everything a scene builds becomes vertex data: `add()` queues MeshData keyed
by (texture, blend) and `build()` merges each queue into one GPU mesh, so a
forest of 150 trees still costs two draw calls. Small things that change
every frame (flames, hands) use `new_dynamic()`, which re-uploads one
modest buffer per update.

The shader knows nothing about specific scenes: vertex colour x tiled
texture, up to 4 point lights, weak directional sun and distance fog.
`render_scale` renders the world at a fraction of the window size (0.5 is
the classic chunky-console look) and the game upscales it.

Frames render offscreen and come back as an opaque RGB pygame Surface -
the window itself stays plain 2D pygame (an OPENGL display mode would eat
all our 2D blits). Adapted from the app's src/core/renderer.py.
"""

import math

import moderngl
import numpy as np
import pygame

MAX_LIGHTS = 8

# the renderer whose GL context is current right now (see Renderer._bind)
_ACTIVE = None

VS = """#version 330
in vec3 in_pos;
in vec3 in_nrm;
in vec2 in_uv;
in vec3 in_col;
uniform mat4 u_mvp;
out vec3 v_world;
out vec3 v_nrm;
out vec2 v_uv;
out vec3 v_col;
void main() {
    v_world = in_pos;
    v_nrm = in_nrm;
    v_uv = in_uv;
    v_col = in_col;
    gl_Position = u_mvp * vec4(in_pos, 1.0);
}
"""

FS = """#version 330
in vec3 v_world;
in vec3 v_nrm;
in vec2 v_uv;
in vec3 v_col;
out vec4 frag;
uniform sampler2D u_tex;
uniform float u_has_tex;
uniform float u_mode;        // 0 = lit opaque, 1 = additive billboard
uniform vec3 u_eye;
uniform vec3 u_amb;
uniform vec3 u_sun_dir;
uniform vec3 u_sun_col;
uniform int u_light_n;
uniform vec3 u_light_pos[8];
uniform vec3 u_light_col[8];
uniform vec3 u_fog_col;
uniform float u_fog_near;
uniform float u_fog_far;

void main() {
    vec3 texc = vec3(1.0);
    float ta = 1.0;
    if (u_has_tex > 0.5) {
        vec4 t = texture(u_tex, v_uv);
        texc = t.rgb;
        ta = t.a;
    }
    vec3 base = v_col * texc;
    float dist = length(v_world - u_eye);
    float f = clamp((dist - u_fog_near) / max(u_fog_far - u_fog_near, 0.001),
                    0.0, 1.0);
    f *= f;
    if (u_mode > 0.5) {
        // unlit premultiplied glow, swallowed by the dark with distance
        frag = vec4(base * ta * (1.0 - f), 1.0);
        return;
    }
    vec3 n = normalize(v_nrm);
    vec3 lit = u_amb * base + base * max(dot(n, u_sun_dir), 0.0) * u_sun_col;
    for (int i = 0; i < 8; i++) {
        if (i >= u_light_n) break;
        vec3 d = u_light_pos[i] - v_world;
        float dl = length(d);
        float att = 1.0 / (1.0 + 0.02 * dl * dl);
        lit += base * max(dot(n, d / max(dl, 0.0001)), 0.0)
               * u_light_col[i] * att;
    }
    frag = vec4(mix(lit, u_fog_col, f), 1.0);
}
"""


def perspective(fov, aspect, near, far):
    """Right-handed perspective projection, column-major numpy array."""
    f = 1.0 / math.tan(fov / 2.0)
    nf = 1.0 / (near - far)
    return np.array([[f / aspect, 0, 0, 0],
                     [0, f, 0, 0],
                     [0, 0, (far + near) * nf, 2 * far * near * nf],
                     [0, 0, -1, 0]], np.float32)


def look_at(eye, yaw, pitch):
    """View matrix for a yaw/pitch camera (yaw 0 looks down +Z).

    Handedness matters: a right-handed camera basis (right x up = back)
    keeps counter-clockwise triangles counter-clockwise in screen space,
    which is what the backface culling in render() relies on. Negating
    `side` here mirrors the frame and every solid then shows its innards.
    """
    cp, sp = math.cos(pitch), math.sin(pitch)
    fwd = np.array([math.sin(yaw) * cp, sp, math.cos(yaw) * cp])
    side = np.array([-math.cos(yaw), 0.0, math.sin(yaw)])
    up = np.cross(side, fwd)
    view = np.eye(4, dtype=np.float32)
    view[0, :3] = side
    view[1, :3] = up
    view[2, :3] = -fwd
    view[0, 3] = -side @ eye
    view[1, 3] = -up @ eye
    view[2, 3] = fwd @ eye
    return view


class DynamicMesh:
    """A small mesh a scene can reshape every frame (flames, flags).
    Buffers are over-allocated once so `update()` is just two writes.
    view_model meshes are authored in camera space and drawn last in the
    opaque pass, two-sided, with the lighting uniforms rotated into that
    same space - a first-person body the eye can never clip through."""

    def __init__(self, renderer, data, texture, blend, view_model=False,
                 on_top=False):
        self.r = renderer
        self.texture = texture
        self.blend = blend
        self.view_model = view_model
        self.on_top = on_top
        self.vao = None
        self._vbo = None
        self._ibo = None
        self.count = 0
        self.update(data)

    def update(self, data):
        acc = _Accum()
        acc.append(data)
        self.r._upload_dynamic(self, acc)

    def dispose(self):
        self.r._bind()
        for obj in (self.vao, self._vbo, self._ibo):
            if obj is not None:
                obj.release()
        self.vao = self._vbo = self._ibo = None
        self.count = 0


class Renderer:
    """Offscreen vertex renderer: build geometry, render a camera, get a
    pygame Surface back."""

    def __init__(self, width, height, render_scale=1.0):
        global _ACTIVE
        self.ctx = moderngl.create_standalone_context()
        _ACTIVE = self
        self.prog = self.ctx.program(vertex_shader=VS, fragment_shader=FS)
        self.size = (max(2, int(width)), max(2, int(height)))
        self.render_scale = max(0.2, min(1.0, float(render_scale)))
        self.textures = {}
        self._pending = {}
        self.groups = []
        self.dynamics = []
        self._make_fbo()
        self._register_white()

    # ------------------------------------------------------------ textures
    def _bind(self):
        """Make this renderer's context the current one.

        A standalone moderngl context is current from the moment it is
        created, so creating a second context leaves the first one's
        objects attached to a context that is no longer active - the editor
        keeps a model viewer and a scene preview alive together, and the
        idle one then draws against the other one's buffers. Re-activating
        at the top of every GL entry point keeps them independent.
        """
        global _ACTIVE
        if _ACTIVE is not self:
            self.ctx.__enter__()
            _ACTIVE = self

    def _register_white(self):
        arr = np.full((2, 2, 3), 255, np.uint8)
        self.texture("white", arr, repeat=False)

    def texture(self, key, arr=None, rgba=False, repeat=True):
        """Cache textures by name; pass a uint8 (H, W, 3/4) array to
        upload (or replace) one."""
        if arr is None:
            return self.textures[key]
        self._bind()
        comp = 4 if rgba else 3
        data = np.ascontiguousarray(np.flipud(arr), dtype=np.uint8)
        h, w = data.shape[:2]
        if key in self.textures:
            self.textures[key].release()
        tex = self.ctx.texture((w, h), comp, data)
        tex.repeat_x = repeat and not rgba
        tex.repeat_y = repeat and not rgba
        tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        if (w & (w - 1)) == 0 and (h & (h - 1)) == 0:
            tex.build_mipmaps()
        else:
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        try:
            tex.anisotropy = 8.0
        except Exception:
            pass
        self.textures[key] = tex
        return tex

    def has_texture(self, key):
        return key in self.textures

    # ----------------------------------------------------------- batching
    def add(self, data, texture="white", blend="opaque"):
        key = (texture, blend)
        buf = self._pending.setdefault(key, _Accum())
        buf.append(data)

    def build(self):
        """Merge every queued MeshData into one VAO per (tex, blend)."""
        self._bind()
        for (texkey, blend), acc in self._pending.items():
            if not acc.idx:
                continue
            if texkey not in self.textures:
                texkey = "white"
            vao, count = self._make_vao(acc, self.textures[texkey])
            self.groups.append((vao, count, texkey, blend))
        self._pending.clear()

    def reset(self):
        self._bind()
        for vao, _c, _t, _b in self.groups:
            vao.release()
        self.groups.clear()
        for d in self.dynamics:
            d.dispose()
        self.dynamics.clear()
        self._pending.clear()

    def dispose(self):
        global _ACTIVE
        self._bind()
        self.reset()
        for tex in self.textures.values():
            tex.release()
        self.textures.clear()
        for att in list(self.fbo.color_attachments) + \
                [self.fbo.depth_attachment]:
            if att is not None:
                att.release()
        self.ctx.release()
        if _ACTIVE is self:
            _ACTIVE = None

    def _make_vao(self, acc, tex):
        ctx = self.ctx
        vbo = ctx.buffer(acc.interleaved().tobytes())
        ibo = ctx.buffer(np.ascontiguousarray(
            acc.idx, np.uint32).tobytes())
        vao = ctx.vertex_array(
            self.prog,
            [(vbo, "3f 3f 2f 3f", "in_pos", "in_nrm", "in_uv", "in_col")],
            ibo)
        return vao, len(acc.idx)

    def new_dynamic(self, data, texture="white", blend="add",
                    view_model=False, on_top=False):
        d = DynamicMesh(self, data, texture, blend, view_model, on_top)
        self.dynamics.append(d)
        return d

    def _upload_dynamic(self, d, acc):
        self._bind()
        payload = acc.interleaved().tobytes()
        ipayload = np.ascontiguousarray(acc.idx, np.uint32).tobytes()
        if d.vao is not None and len(payload) == d._vbo.size \
                and len(ipayload) == d._ibo.size:
            # same topology, just new vertex soup: rewrite in place
            d._vbo.write(payload)
            d._ibo.write(ipayload)
            d.count = len(acc.idx)
            return
        if d.vao is not None:
            d.dispose()
        # exact-size buffers so render() walks precisely our indices
        d._vbo = self.ctx.buffer(payload)
        d._ibo = self.ctx.buffer(ipayload)
        d.vao = self.ctx.vertex_array(
            self.prog,
            [(d._vbo, "3f 3f 2f 3f",
              "in_pos", "in_nrm", "in_uv", "in_col")],
            d._ibo)
        d.count = len(acc.idx)

    # ------------------------------------------------------------- resize
    def _target_size(self):
        w, h = self.size
        return (max(2, int(w * self.render_scale)),
                max(2, int(h * self.render_scale)))

    def _make_fbo(self):
        ctx = self.ctx
        self.target = self._target_size()
        self.color = ctx.renderbuffer(self.target)
        self.depth = ctx.depth_renderbuffer(self.target)
        self.fbo = ctx.framebuffer(color_attachments=[self.color],
                                   depth_attachment=self.depth)

    def resize(self, w, h):
        w, h = max(2, int(w)), max(2, int(h))
        if (w, h) == self.size:
            return
        self._bind()
        for att in list(self.fbo.color_attachments) + \
                [self.fbo.depth_attachment]:
            if att is not None:
                att.release()
        self.size = (w, h)
        self._make_fbo()

    def set_render_scale(self, scale):
        scale = max(0.2, min(1.0, float(scale)))
        if abs(scale - self.render_scale) < 1e-4:
            return
        self.render_scale = scale
        self._bind()
        for att in list(self.fbo.color_attachments) + \
                [self.fbo.depth_attachment]:
            if att is not None:
                att.release()
        self._make_fbo()

    # --------------------------------------------------------------- stats
    def stats(self):
        """Counters for the debug overlay (triangles, batches, targets)."""
        static_tris = sum(count for _v, count, _t, _b in self.groups) // 3
        dynamic_tris = sum(d.count for d in self.dynamics
                           if d.vao is not None and d.count) // 3
        return {
            "batches": len(self.groups),
            "draw_calls": len(self.groups) + len(
                [d for d in self.dynamics if d.vao is not None and d.count]),
            "triangles": static_tris + dynamic_tris,
            "static_tris": static_tris,
            "dynamic_tris": dynamic_tris,
            "dynamics": len(self.dynamics),
            "textures": len(self.textures),
            "render_scale": self.render_scale,
            "target": tuple(self.target),
            "size": tuple(self.size),
        }

    # -------------------------------------------------------------- frame
    def _matrix(self, eye, yaw, pitch, fov):
        w, h = self.target
        proj = perspective(math.radians(fov), w / h, 0.05, 800.0)
        view = look_at(np.asarray(eye, np.float64), yaw, pitch)
        return proj, view

    def render(self, eye, yaw, pitch, scene):
        """Draw the loaded scene from the camera and hand back a Surface
        at the internal (render_scale) resolution."""
        ctx = self.ctx
        self._bind()
        self.fbo.use()
        cc = getattr(scene, "clear_color", (0.02, 0.02, 0.03))
        ctx.clear(cc[0], cc[1], cc[2], 1.0)
        ctx.enable(moderngl.DEPTH_TEST)

        w, h = self.target
        fov = getattr(scene, "fov", 72.0)
        proj, view = self._matrix(eye, yaw, pitch, fov)
        mvp = np.ascontiguousarray((proj @ view).T, dtype=np.float32)
        prog = self.prog
        prog["u_mvp"].write(mvp)
        prog["u_eye"].write(np.asarray(eye, np.float32))
        prog["u_amb"].write(np.asarray(
            getattr(scene, "ambient", (0.2, 0.2, 0.2)), np.float32))
        sd = np.asarray(getattr(scene, "sun_dir", (0.4, 0.8, 0.3)),
                        np.float64)
        sdv = sd / max(np.linalg.norm(sd), 1e-6)
        prog["u_sun_dir"].write(np.asarray(sdv, np.float32))
        prog["u_sun_col"].write(np.asarray(
            getattr(scene, "sun_col", (0.2, 0.2, 0.2)), np.float32))
        fc = getattr(scene, "fog_color", (0.05, 0.05, 0.07))
        prog["u_fog_col"].write(np.asarray(fc, np.float32))
        prog["u_fog_near"].value = float(getattr(scene, "fog_near", 60.0))
        prog["u_fog_far"].value = float(getattr(scene, "fog_far", 260.0))

        # a merged level holds far more lights than the shader can take,
        # so upload the ones nearest the eye and let the rest fade out
        lights = list(getattr(scene, "lights", []))
        if len(lights) > MAX_LIGHTS:
            ex, ey, ez = float(eye[0]), float(eye[1]), float(eye[2])
            lights.sort(key=lambda L: (L["pos"][0] - ex) ** 2 +
                       (L["pos"][1] - ey) ** 2 + (L["pos"][2] - ez) ** 2)
        lights = lights[:MAX_LIGHTS]
        lp = np.zeros((MAX_LIGHTS, 3), np.float32)
        lc = np.zeros((MAX_LIGHTS, 3), np.float32)
        for i, L in enumerate(lights):
            lp[i] = L["pos"]
            lc[i] = L["color"]
        prog["u_light_pos"].write(lp)
        prog["u_light_col"].write(lc)
        prog["u_light_n"].value = len(lights)

        # lit, depth-sorted opaque batch
        ctx.enable(moderngl.CULL_FACE)
        ctx.disable(moderngl.BLEND)
        prog["u_mode"].value = 0.0
        for vao, count, texkey, blend in self.groups:
            if blend != "opaque":
                continue
            prog["u_has_tex"].value = 0.0 if texkey == "white" else 1.0
            self.textures[texkey].use()
            vao.render(moderngl.TRIANGLES)
        # reshaped-per-frame lit geometry (world-space)
        for d in self.dynamics:
            if d.blend != "opaque" or d.view_model \
                    or d.vao is None or not d.count:
                continue
            prog["u_has_tex"].value = 0.0 if d.texture == "white" else 1.0
            self.textures.get(d.texture, self.textures["white"]).use()
            d.vao.render(moderngl.TRIANGLES)
        # view-model bodies: vertices already live in camera space, so
        # the pass runs proj-only and the lighting uniforms get rotated
        # into that space; two-sided so the inside never shows through
        vms = [d for d in self.dynamics
               if d.blend == "opaque" and d.view_model
               and d.vao is not None and d.count]
        if vms:
            m = view[:3, :3]
            prog["u_mvp"].write(np.ascontiguousarray(proj.T, np.float32))
            prog["u_eye"].write(np.zeros(3, np.float32))
            prog["u_sun_dir"].write(np.asarray(m @ sdv, np.float32))
            prog["u_light_pos"].write(
                np.asarray((lp - np.asarray(eye, np.float32)) @ m.T,
                           np.float32))
            ctx.disable(moderngl.CULL_FACE)
            for d in vms:
                if d.on_top:
                    continue
                prog["u_has_tex"].value = \
                    0.0 if d.texture == "white" else 1.0
                self.textures.get(d.texture, self.textures["white"]).use()
                d.vao.render(moderngl.TRIANGLES)
            # on-top view models (FPS hands): depth test off, so they
            # are never buried in the chest or a wall in front of them;
            # they still write depth, keeping the additive sky from
            # shining through the arms. (moderngl's ctx.depth_test
            # property is a dead stub; only enable/disable reach the GL)
            if any(d.on_top for d in vms):
                ctx.disable(moderngl.DEPTH_TEST)
                for d in vms:
                    if not d.on_top:
                        continue
                    prog["u_has_tex"].value = \
                        0.0 if d.texture == "white" else 1.0
                    self.textures.get(d.texture,
                                      self.textures["white"]).use()
                    d.vao.render(moderngl.TRIANGLES)
                ctx.enable(moderngl.DEPTH_TEST)
            ctx.enable(moderngl.CULL_FACE)
            # put the world uniforms back for the additive pass
            prog["u_mvp"].write(mvp)
            prog["u_eye"].write(np.asarray(eye, np.float32))
            prog["u_sun_dir"].write(np.asarray(sdv, np.float32))
            prog["u_light_pos"].write(lp)

        # glows: additive and double-sided, drawn after every opaque
        # surface so depth already holds the real geometry; moderngl
        # exposes no depth mask, but late additive writes are harmless
        ctx.disable(moderngl.CULL_FACE)
        ctx.enable(moderngl.BLEND)
        # ADDITIVE_BLENDING is (ONE, ONE); the shader emits premultiplied
        # glow colour, so straight-add is the right composite
        ctx.blend_func = moderngl.ADDITIVE_BLENDING
        prog["u_mode"].value = 1.0
        for vao, count, texkey, blend in self.groups:
            if blend != "add":
                continue
            prog["u_has_tex"].value = 1.0
            self.textures.get(texkey, self.textures["white"]).use()
            vao.render(moderngl.TRIANGLES)
        for d in self.dynamics:
            if d.blend != "add" or d.vao is None or not d.count:
                continue
            prog["u_has_tex"].value = 1.0 if d.texture != "white" else 0.0
            self.textures.get(d.texture, self.textures["white"]).use()
            d.vao.render(moderngl.TRIANGLES)

        ctx.disable(moderngl.BLEND)

        data = self.fbo.read(components=3)
        arr = np.frombuffer(data, np.uint8).reshape(h, w, 3)
        # RGB (not RGBA): the frame must be fully opaque so stale pixels
        # from the previous screen never blend through
        return pygame.image.fromstring(
            np.ascontiguousarray(arr[::-1]).tobytes(), (w, h), "RGB")


class _Accum:
    """Merge-friendly pile of MeshData with flat list storage."""

    def __init__(self):
        self.pos = []
        self.nrm = []
        self.uv = []
        self.col = []
        self.idx = []

    def append(self, m):
        base = len(self.pos)
        self.pos.extend(m.pos)
        self.nrm.extend(m.nrm)
        self.uv.extend(m.uv)
        self.col.extend(m.col)
        self.idx.extend([i + base for i in m.idx])

    def interleaved(self):
        n = len(self.pos)
        out = np.empty((n, 11), np.float32)
        out[:, 0:3] = self.pos
        out[:, 3:6] = self.nrm
        out[:, 6:8] = self.uv
        out[:, 8:11] = self.col
        return out
