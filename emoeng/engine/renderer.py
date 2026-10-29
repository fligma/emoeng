"""Vertex-based moderngl renderer."""

import math

import moderngl
import numpy as np
import pygame

from . import (colors, lights as lightmod, meshes, proctex,
               shaders as shadermod)

MAX_LIGHTS = 8

# draw order: opaque, trans, panel, add, alpha, light, hud
BLENDS = ("opaque", "trans", "panel", "add", "alpha", "light", "hud")

# layers wearing scene lighting, so sheet tiles apply
LIT_BLENDS = ("opaque", "trans")

# what a 2D scene's light mask starts at: nearly dark
DEFAULT_AMBIENT2D = (0.12, 0.12, 0.14)

# frustum defaults when neither camera nor caller says
DEFAULT_FOV = 68.0
DEFAULT_NEAR = 0.05
DEFAULT_FAR = 800.0
# default lightmap edge in pixels, a power of two
DEFAULT_LM_SIZE = 1024
# internal resolution as a fraction of the window
MIN_SCALE = 0.2
MAX_SCALE = 1.0

# the renderer whose GL context is current
_ACTIVE = None

VS = """#version 330
in vec3 in_pos;
in vec3 in_nrm;
in vec2 in_uv;
in vec2 in_uv2;
in vec4 in_col;
uniform mat4 u_mvp;
out vec3 v_world;
out vec3 v_nrm;
out vec2 v_uv;
out vec2 v_lm;
out vec4 v_col;
void main() {
    v_world = in_pos;
    v_nrm = in_nrm;
    v_uv = in_uv;
    v_lm = in_uv2;
    v_col = in_col;
    gl_Position = u_mvp * vec4(in_pos, 1.0);
}
"""

FS = """#version 330
in vec3 v_world;
in vec3 v_nrm;
in vec2 v_uv;
in vec2 v_lm;
in vec4 v_col;
out vec4 frag;
uniform sampler2D u_tex;
uniform float u_has_tex;
uniform sampler2D u_lm;         // a baked-light map, sampled on v_lm
uniform float u_has_lm;         // 1.0 when one is bound
uniform float u_mode;        // 0 = lit, 1 = additive billboard,
                              // 2 = unlit straight-alpha (2D / UI),
                              // 3 = into the 2D light mask
                              // (the lit modes 0 and 2 are what the two
                              // blended 3D layers use; see render())
uniform float u_boost;        // a light's own energy, for mode 3
uniform vec3 u_eye;
uniform vec3 u_amb;
uniform vec3 u_sun_dir;
uniform vec3 u_sun_col;
uniform int u_light_n;
uniform vec3 u_light_pos[8];
uniform vec3 u_light_col[8];
uniform vec3 u_light_dir[8];
uniform vec4 u_light_shape[8];  // radius, cos inner, cos outer, kind
uniform vec3 u_fog_col;
uniform float u_fog_near;
uniform float u_fog_far;
uniform vec4 u_light_atten[8];    // mode, falloff start, exponent, tube length
uniform sampler2D u_cookie;       // a pattern projected through a light
uniform float u_has_cookie;
uniform int u_cookie_slot;        // which 3D light owns it (-1: none)

// the falloff curve, shared with lights.atten_value so a CPU query and the
// picture agree; radius 0 keeps the classic inverse-square the old scenes use
float att_of(float dl, vec4 sh, vec4 ap) {
    if (sh.x <= 0.0) return 1.0 / (1.0 + 0.02 * dl * dl);
    float mode = ap.x;
    if (mode > 3.5) return dl <= sh.x ? 1.0 : 0.0;
    float t = clamp(dl / sh.x, 0.0, 1.0);
    float s = clamp(ap.y, 0.0, 0.95);
    float u = clamp((t - s) / max(0.001, 1.0 - s), 0.0, 1.0);
    if (mode > 0.5 && mode < 1.5) return 1.0 - u;
    if (mode > 1.5 && mode < 2.5) return pow(1.0 - u, max(0.01, ap.z));
    if (mode > 2.5) return 1.0 / (1.0 + max(0.05, ap.z) * t * t);
    return (1.0 - u) * (1.0 - u);
}

// any vector at right angles to this one, without the cross-product-with-up
// trap that fails when the light points straight up or down
vec3 perp3(vec3 v) {
    vec3 a = abs(v.x) > 0.9 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0);
    return normalize(cross(v, a));
}

void main() {
    vec3 texc = vec3(1.0);
    float ta = 1.0;
    if (u_has_tex > 0.5) {
        vec4 t = texture(u_tex, v_uv);
        texc = t.rgb;
        ta = t.a;
    }
    vec3 base = v_col.rgb * texc;
    // one coverage for every mode: the vertex alpha is an object's own
    // opacity and the picture's alpha is its shape, and a thing is only
    // as see-through as both of them let it be
    float cover = clamp(ta * v_col.a, 0.0, 1.0);
    // a hole is a hole in every layer: a texel carrying nothing is dropped
    // rather than painted, so a cut-out sheet never lays a slab of its own
    // background over the world behind it
    if (cover <= 0.004) discard;
    float dist = length(v_world - u_eye);
    float f = clamp((dist - u_fog_near) / max(u_fog_far - u_fog_near, 0.001),
                    0.0, 1.0);
    f *= f;
    if (u_mode > 2.5) {
        // into the light mask: the gradient's alpha is the falloff and
        // `u_boost` the light's energy. A positive boost adds itself to the
        // mask; a negative one cannot (fixed-point colours clamp at zero),
        // so a dark pool emits the *complement* and the pass multiplies
        frag = vec4(clamp(1.0 + base * ta * u_boost, 0.0, 1.0), 1.0);
        if (u_boost < 0.0) {
            return;
        }
        vec3 c = base * ta;
        if (u_has_cookie > 0.5) {
            c *= texture(u_cookie, v_uv).rgb;
        }
        frag = vec4(c * u_boost, 1.0);
        return;
    }
    if (u_mode > 1.5) {
        // unlit sprite/panel: colour x texture, kept alpha is the coverage
        frag = vec4(base, cover);
        return;
    }
    if (u_mode > 0.5) {
        // unlit premultiplied glow, swallowed by the dark with distance
        frag = vec4(base * cover * (1.0 - f), 1.0);
        return;
    }
    vec3 n = normalize(v_nrm);
    // the flat ambient every unbaked face already wears; a lightmap that
    // is bound stands in for it, carrying ambient plus the baked lights
    // already multiplied in, so one surface is lit the same live or baked
    vec3 lm = mix(u_amb, texture(u_lm, v_lm).rgb, u_has_lm);
    vec3 lit = base * lm
               + base * max(dot(n, u_sun_dir), 0.0) * u_sun_col;
    for (int i = 0; i < 8; i++) {
        if (i >= u_light_n) break;
        vec4 sh = u_light_shape[i];
        int shp = int(sh.w + 0.5);       // 0 point, 1 spot, 2 sun, 7 tube
        vec3 lv;
        float att;
        vec3 lcol = u_light_col[i];
        vec3 ldir = normalize(u_light_dir[i]);
        vec3 d = u_light_pos[i] - v_world;
        if (shp == 2) {
            // a sun: every point sees the same direction, no distance loss
            lv = -ldir;
            att = 1.0;
        } else {
            float dl = length(d);
            if (shp == 7) {
                // a tube: measure to the nearest point of its line, and let
                // the last 15% at either end fade the light out
                float len = max(1e-3, u_light_atten[i].w);
                vec3 v = -d;
                float along = clamp(dot(v, ldir), 0.0, len);
                vec3 to = d + ldir * along;
                dl = length(to);
                if (dl < 1e-3) {
                    // exactly on the axis: the nearest point gives no
                    // direction, so aim at the middle of the tube instead
                    to = u_light_pos[i] + ldir * (0.5 * len) - v_world;
                    dl = max(1e-3, length(to));
                }
                to /= dl;
                att = att_of(dl, sh, u_light_atten[i]);
                att *= clamp(min(along, len - along)
                             / max(1e-3, 0.15 * len), 0.0, 1.0);
                lv = to;
            } else {
                lv = d / max(dl, 0.0001);
                att = att_of(dl, sh, u_light_atten[i]);
            }
            if (shp == 1) {
                // a spot: cut the cone, and soften between inner and outer
                float c = dot(-ldir, lv);
                att *= smoothstep(sh.z, sh.y, c);
                if (u_has_cookie > 0.5 && i == u_cookie_slot && sh.z > 0.05) {
                    // a pattern thrown through the cone: find where across
                    // the cone this point sits, at its own depth
                    vec3 sidev = perp3(ldir);
                    vec3 upv = normalize(cross(ldir, sidev));
                    float depth = max(0.001, dot(-d, ldir));
                    float wide = depth * sqrt(max(0.0, 1.0 - sh.z * sh.z))
                                 / max(0.02, sh.z);
                    vec2 puv = 0.5 + vec2(dot(-d, sidev), dot(-d, upv))
                               / max(0.001, 2.0 * wide);
                    lcol *= texture(u_cookie, puv).rgb;
                }
            }
        }
        lit += base * max(dot(n, lv), 0.0) * lcol * att;
    }
    frag = vec4(mix(lit, u_fog_col, f), cover);
}
"""

VS_BLIT = """#version 330
in vec2 in_pos;              // 0..1 across a unit quad
out vec2 v_uv;
uniform vec4 u_box;          // the viewport's (x0, y0, x1, y1) in uv, GL-wise
void main() {
    v_uv = mix(u_box.xy, u_box.zw, in_pos);
    gl_Position = vec4(v_uv * 2.0 - 1.0, 0.0, 1.0);
}
"""

FS_BLIT = """#version 330
in vec2 v_uv;
out vec4 frag;
uniform sampler2D u_tex;
void main() {
    frag = texture(u_tex, v_uv);
}
"""

# a screen panel's mixer: shape mask, tint, brightness
FS_PANEL = """#version 330
in vec2 v_uv;
out vec4 frag;
uniform sampler2D u_tex;
uniform vec2 u_size;         // panel size in pixels, for the shape maths
uniform int u_shape;         // 0 rect, 1 round, 2 circle, 3 soft
uniform vec3 u_tint;         // panel colour multiply (1,1,1) = plain
uniform float u_bright;      // panel brightness
uniform float u_has_src;     // 0 paints a blank masked panel

void main() {
    float mask = 1.0;
    if (u_shape == 1 || u_shape == 2 || u_shape == 3) {
        vec2 xy = v_uv * u_size;
        float w = u_size.x;
        float h = u_size.y;
        if (u_shape == 2) {
            vec2 d = (xy - vec2(w, h) * 0.5) / (vec2(w, h) * 0.5);
            mask = dot(d, d) <= 1.0 ? 1.0 : 0.0;
        } else if (u_shape == 1) {
            float rad = 0.10 * min(w, h);
            vec2 q = xy - vec2(clamp(xy.x, rad, w - rad),
                               clamp(xy.y, rad, h - rad));
            mask = length(q) <= rad ? 1.0 : 0.0;
        } else {
            float edge = min(min(xy.x, w - xy.x), min(xy.y, h - xy.y));
            mask = clamp(edge / max(2.0, 0.08 * min(w, h)), 0.0, 1.0);
        }
    }
    if (u_has_src < 0.5) {
        frag = vec4(0.0, 0.0, 0.0, mask);
        return;
    }
    vec3 c = texture(u_tex, v_uv).rgb;
    frag = vec4(clamp(c * u_tint * u_bright, 0.0, 1.0), mask);
}
"""

# the bake pass: a model's surface into its lightmap
BAKE_VS = """#version 330
in vec3 in_pos;
in vec3 in_nrm;
in vec2 in_uv2;
out vec3 v_world;
out vec3 v_nrm;
void main() {
    v_world = in_pos;
    v_nrm = in_nrm;
    gl_Position = vec4(in_uv2 * 2.0 - 1.0, 0.0, 1.0);
}
"""

BAKE_FS = """#version 330
in vec3 v_world;
in vec3 v_nrm;
out vec4 frag;
uniform vec3 u_amb;
uniform int u_light_n;
uniform vec3 u_light_pos[8];
uniform vec3 u_light_col[8];
uniform vec3 u_light_dir[8];
uniform vec4 u_light_shape[8];
uniform vec4 u_light_atten[8];
uniform sampler2D u_cookie;
uniform float u_has_cookie;
uniform int u_cookie_slot;

float att_of(float dl, vec4 sh, vec4 ap) {
    if (sh.x <= 0.0) return 1.0 / (1.0 + 0.02 * dl * dl);
    float mode = ap.x;
    if (mode > 3.5) return dl <= sh.x ? 1.0 : 0.0;
    float t = clamp(dl / sh.x, 0.0, 1.0);
    float s = clamp(ap.y, 0.0, 0.95);
    float u = clamp((t - s) / max(0.001, 1.0 - s), 0.0, 1.0);
    if (mode > 0.5 && mode < 1.5) return 1.0 - u;
    if (mode > 1.5 && mode < 2.5) return pow(1.0 - u, max(0.01, ap.z));
    if (mode > 2.5) return 1.0 / (1.0 + max(0.05, ap.z) * t * t);
    return (1.0 - u) * (1.0 - u);
}

vec3 perp3(vec3 v) {
    vec3 a = abs(v.x) > 0.9 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0);
    return normalize(cross(v, a));
}

void main() {
    vec3 n = normalize(v_nrm);
    vec3 acc = u_amb;
    for (int i = 0; i < 8; i++) {
        if (i >= u_light_n) break;
        vec4 sh = u_light_shape[i];
        int shp = int(sh.w + 0.5);
        vec3 lv;
        float att;
        vec3 lcol = u_light_col[i];
        vec3 ldir = normalize(u_light_dir[i]);
        vec3 d = u_light_pos[i] - v_world;
        if (shp == 2) {
            lv = -ldir;
            att = 1.0;
        } else {
            float dl = length(d);
            if (shp == 7) {
                float len = max(1e-3, u_light_atten[i].w);
                vec3 v = -d;
                float along = clamp(dot(v, ldir), 0.0, len);
                vec3 to = d + ldir * along;
                dl = length(to);
                if (dl < 1e-3) {
                    to = u_light_pos[i] + ldir * (0.5 * len) - v_world;
                    dl = max(1e-3, length(to));
                }
                to /= dl;
                att = att_of(dl, sh, u_light_atten[i]);
                att *= clamp(min(along, len - along)
                             / max(1e-3, 0.15 * len), 0.0, 1.0);
                lv = to;
            } else {
                lv = d / max(dl, 0.0001);
                att = att_of(dl, sh, u_light_atten[i]);
            }
            if (shp == 1) {
                float c = dot(-ldir, lv);
                att *= smoothstep(sh.z, sh.y, c);
                if (u_has_cookie > 0.5 && i == u_cookie_slot
                        && sh.z > 0.05) {
                    vec3 sidev = perp3(ldir);
                    vec3 upv = normalize(cross(ldir, sidev));
                    float depth = max(0.001, dot(-d, ldir));
                    float wide = depth * sqrt(max(0.0, 1.0 - sh.z * sh.z))
                                 / max(0.02, sh.z);
                    vec2 puv = 0.5 + vec2(dot(-d, sidev), dot(-d, upv))
                               / max(0.001, 2.0 * wide);
                    lcol *= texture(u_cookie, puv).rgb;
                }
            }
        }
        acc += max(dot(n, lv), 0.0) * lcol * att;
    }
    frag = vec4(clamp(acc, 0.0, 1.0), 1.0);
}
"""

# panel shapes FS_PANEL cuts by, as screens name them
SHAPE_CODES = {"rect": 0, "round": 1, "circle": 2, "soft": 3}


def wants_int(uni):
    """Whether a uniform stores a whole number."""
    fmt = "".join(c for c in str(getattr(uni, "fmt", "f")) if c.isalpha())
    return fmt[:1] in ("i", "I")


def write_uniform(prog, name, value):
    """Set one uniform; report whether it was declared."""
    uni = prog.get(name, None)
    if uni is None or value is None:
        return False
    if isinstance(value, (tuple, list)):
        uni.value = tuple(int(v) if wants_int(uni) else float(v)
                          for v in value)
    elif isinstance(value, (bool, int, float)):
        uni.value = int(value) if wants_int(uni) else float(value)
    else:                       # an array: a matrix, mostly
        uni.write(np.ascontiguousarray(value, np.float32))
    return True


def clamp_scale(scale):
    """Keep the internal resolution inside the usable band."""
    return max(MIN_SCALE, min(MAX_SCALE, float(scale)))


def perspective(fov, aspect, near, far):
    """Right-handed perspective projection, column-major numpy array."""
    f = 1.0 / math.tan(fov / 2.0)
    nf = 1.0 / (near - far)
    return np.array([[f / aspect, 0, 0, 0],
                     [0, f, 0, 0],
                     [0, 0, (far + near) * nf, 2 * far * near * nf],
                     [0, 0, -1, 0]], np.float32)


def orthographic(left, right, bottom, top, near, far):
    """Right-handed orthographic projection, column-major numpy array."""
    rl = 1.0 / (right - left)
    tb = 1.0 / (top - bottom)
    fn = 1.0 / (far - near)
    return np.array([[2 * rl, 0, 0, -(right + left) * rl],
                     [0, 2 * tb, 0, -(top + bottom) * tb],
                     [0, 0, -2 * fn, -(far + near) * fn],
                     [0, 0, 0, 1]], np.float32)


def look_at(eye, yaw, pitch, roll=0.0):
    """View matrix for a yaw/pitch camera."""
    eye = np.asarray(eye, np.float64)
    cp, sp = math.cos(pitch), math.sin(pitch)
    fwd = np.array([math.sin(yaw) * cp, sp, math.cos(yaw) * cp])
    side = np.array([-math.cos(yaw), 0.0, math.sin(yaw)])
    up = np.cross(side, fwd)
    if roll:
        cr, sr = math.cos(roll), math.sin(roll)
        side, up = side * cr - up * sr, up * cr + side * sr
    view = np.eye(4, dtype=np.float32)
    view[0, :3] = side
    view[1, :3] = up
    view[2, :3] = -fwd
    view[0, 3] = -side @ eye
    view[1, 3] = -up @ eye
    view[2, 3] = fwd @ eye
    return view


class DynamicMesh:
    """A mesh a scene can reshape every frame (flames, flags)."""

    @staticmethod
    def strip_uv(uv):
        """A uv fit on its own; its pin, if it carried one, is not wanted."""
        if uv is None or len(uv) <= 4:
            return uv
        return tuple(uv[:4])

    def __init__(self, renderer, data, texture, blend, view_model=False,
                 on_top=False, opacity=1.0, shader=None, uv=None,
                 anchor=None, frame=None):
        self.r = renderer
        self._layer0 = blend       # the layer the caller asked for
        self.opacity = renderer.opacity_of(opacity)
        # the sheet has a say too, so this picks the layer rather than copy it
        self.texture = texture
        self.view_model = view_model
        self.on_top = on_top
        pin = anchor or (uv[4] if uv is not None and len(uv) > 4 else None)
        self.uv = self.strip_uv(uv)   # (tile, scale, offset, spin), or None
        # where the metre sheet is pinned; latched, so a reshape cannot
        # drift it. `frame` is a callable that says where the body stands
        # now, so a body that moves or turns carries its picture with it
        self.anchor = pin
        self.frame = frame
        # only a 2D light mesh uses these: energy and pattern
        self.boost = 1.0
        self.cookie = None
        # a baked-light key sampled on uv2; None means lit live
        self.lightmap = None
        self.vao = None
        self._vbo = None
        self._ibo = None
        self._data = None         # the last soup uploaded, for a fade
        self._prog = None         # ... and the program it was built for
        self.count = 0
        self.shader = None
        self.shader_prog = None
        self.set_shader(shader)
        self.update(data)

    def set_shader(self, shader):
        """Wear a `uv` shader, or none; others are dropped."""
        pas = self.r.shader_pass(shader)
        prog = None
        if pas is not None and pas.mode == "uv":
            prog = pas.program(self.r)
        if prog is self.shader_prog:
            return self
        self.shader = pas if prog is not None else None
        self.shader_prog = prog
        if self._data is not None:
            self.update(self._data)
        return self

    # re-assigning `texture` changes sheet or switches to colour
    @property
    def texture(self):
        return self._texture

    @texture.setter
    def texture(self, value):
        self._texture = self.r.color_texture(value)
        if getattr(self, "_layer0", None) is not None:
            self.relayer()

    def relayer(self):
        """Re-pick the draw layer: what was asked, the fade, the picture."""
        self.blend = self.r.layer_for(self._layer0, self.opacity,
                                      self._texture)
        return self

    def update(self, data):
        self._data = data
        if self.frame is not None:
            self.anchor = self.frame()
        if self.anchor is None:
            self.anchor = meshes.mesh_anchor(data)
        acc = _Accum()
        acc.append(data, self.opacity,
                  self.r.uv_for(self._texture, self.blend, self.uv,
                                self.anchor))
        self.r._upload_dynamic(self, acc)

    def set_uv(self, uv):
        """Re-map this mesh's texture without touching its shape."""
        self.uv = self.strip_uv(uv)
        if self._data is not None:
            self.update(self._data)
        return self

    def set_opacity(self, opacity):
        """Fade this mesh to a new solidity, no rebuild."""
        self.r.fade(self, opacity)
        if self._data is not None:
            self.update(self._data)
        return self

    def dispose(self):
        self.r._bind()
        for obj in (self.vao, self._vbo, self._ibo):
            if obj is not None:
                obj.release()
        self.vao = self._vbo = self._ibo = None
        self.count = 0


class Renderer:
    """Offscreen vertex renderer: build geometry, render a camera, get a"""

    # the project shader names resolve against; None means pre-resolved
    project = None

    def __init__(self, width, height, render_scale=1.0, share=None,
                 windowed=False):
        """Make a renderer."""
        global _ACTIVE
        self.windowed = bool(windowed) and share is None
        self.shared = share
        if share is not None:
            self.ctx = share.ctx
            self.textures = share.textures
        elif self.windowed:
            # adopt the window's context: draw and swap, no copy
            self.ctx = moderngl.create_context()
            self.textures = {}
            _ACTIVE = self
        else:
            self.ctx = moderngl.create_standalone_context()
            self.textures = {}
            _ACTIVE = self
        self.prog = self.ctx.program(vertex_shader=VS, fragment_shader=FS)
        self.prog["u_tex"].value = 0
        self.prog["u_cookie"].value = 1
        self.prog["u_lm"].value = 2       # a lightmap rides on a third unit
        self.prog["u_has_lm"].value = 0.0  # until a batch says otherwise
        self.prog["u_has_cookie"].value = 0.0
        self.prog["u_cookie_slot"].value = -1
        self.prog_blit = self.ctx.program(vertex_shader=VS_BLIT,
                                          fragment_shader=FS_BLIT)
        self.prog_panel = self.ctx.program(vertex_shader=VS_BLIT,
                                           fragment_shader=FS_PANEL)
        self.prog_panel["u_tex"].value = 0
        self.prog_panel["u_box"].value = (0.0, 0.0, 1.0, 1.0)
        self.prog_panel["u_size"].value = (1.0, 1.0)
        self.prog_panel["u_shape"].value = 0
        self.prog_panel["u_tint"].value = (1.0, 1.0, 1.0)
        self.prog_panel["u_bright"].value = 1.0
        self.prog_panel["u_has_src"].value = 1.0
        # the bake rig: one throwaway program for lightmaps
        self.prog_bake = self.ctx.program(vertex_shader=BAKE_VS,
                                          fragment_shader=BAKE_FS)
        self.prog_bake["u_cookie"].value = 1
        self.prog_bake["u_has_cookie"].value = 0.0
        self.prog_bake["u_cookie_slot"].value = -1
        # True once bake lights moved into a map
        self.baked_lights = False
        self.size = (max(2, int(width)), max(2, int(height)))
        self.render_scale = clamp_scale(render_scale)
        self._light_tex = {}        # gradient cache, keyed by falloff
        self.tile = {}              # texture key -> metres per sheet repeat
        self.holes = {}             # texture key -> sheet shows through
        self._pending = {}
        self._live = {}             # claim -> DynamicMesh (editor drags)
        self.groups = []
        self.dynamics = []
        self.viewport = None          # last rect rendered, in target pixels
        self.camera = None            # last camera, when one was passed
        self.frame_array = None       # the pixels behind the last Surface
        self._read_buf = None         # ... and the buffer they are read into
        self._read_key = None
        self.lfbo = None              # the 2D light mask (made when needed)
        self.ltex = None
        self.pbo = None               # the shader chain's two targets,
        self.ptex = None              # written in turn so a chain of three
        self.qbo = None               # still costs two buffers
        self.qtex = None
        self._post = ()               # the armed shader passes
        self._post_frame = 0          # a shader's `g.seed` rolls on this
        self.time = 0.0               # the clock a shader reads (`g.time`)
        self._shader_progs = []       # programs built for project shaders
        self._shader_quads = {}       # ... and the unit quad each one draws
        self._panel = {}              # composites: key -> (texture, fbo)
        self.gpu_only = False         # render() leaves the frame on the GPU
        self.last_out = None          # ... and names the texture here
        self._mvp = None              # the matrix the current pass uses,
        self._eye = None              # so a mesh's own program can match it
        self.quad = self._make_quad()
        self.quad_panel = self.ctx.vertex_array(
            self.prog_panel,
            [(self.quad_vbo, "2f", "in_pos")], self.quad_ibo)
        self._make_fbo()
        if share is None:
            # a sharing rig draws among the parent's sheets already
            self._register_white()

    def _make_quad(self):
        """A unit quad in the corner-to-corner 0..1 space `VS_BLIT` wants."""
        self.quad_vbo = self.ctx.buffer(
            np.array([[0, 0], [1, 0], [1, 1], [0, 1]],
                     np.float32).tobytes())
        self.quad_ibo = self.ctx.buffer(
            np.array([0, 1, 2, 0, 2, 3], np.uint32).tobytes())
        return self.ctx.vertex_array(
            self.prog_blit, [(self.quad_vbo, "2f", "in_pos")],
            self.quad_ibo)

    def _bind(self):
        """Make this renderer's context the current one."""
        if self.shared is not None:
            self.shared._bind()
            return
        global _ACTIVE
        if _ACTIVE is not self:
            self.ctx.__enter__()
            _ACTIVE = self

    def _register_white(self):
        arr = np.full((2, 2, 3), 255, np.uint8)
        self.texture("white", arr, repeat=False)

    def texture(self, key, arr=None, rgba=False, repeat=True,
                filter="linear", mipmaps=True, tile=0.0):
        """Cache textures by name; accept uint8 (H, W, 3/4).

        A sheet with see-through pixels is remembered as `holes`, which is
        what lets a cut-out be drawn blended rather than as a solid slab.
        Such a sheet still tiles: an alpha channel is not a reason to clamp
        a floor to one picture, and only a non-square sheet without mipmaps
        has to, since GL cannot wrap those.
        """
        if arr is None:
            return self.textures[key]
        self._bind()
        try:
            self.tile[key] = max(0.0, float(tile or 0.0))
        except (TypeError, ValueError):
            self.tile[key] = 0.0
        comp = 4 if rgba else 3
        data = np.ascontiguousarray(np.flipud(arr), dtype=np.uint8)
        if data.ndim == 3 and data.shape[2] >= 4:
            comp = 4          # the picture itself decides; a flag can lie
        h, w = data.shape[:2]
        self.holes[key] = comp == 4 and bool(data[..., 3].min() < 250)
        if key in self.textures:
            self.textures[key].release()
        tex = self.ctx.texture((w, h), comp, data)
        pow2 = (w & (w - 1)) == 0 and (h & (h - 1)) == 0
        wrap = bool(repeat) and (comp == 3 or pow2 or not mipmaps)
        tex.repeat_x = tex.repeat_y = wrap
        nearest = str(filter).lower() == "nearest"
        if mipmaps and pow2 and not nearest:
            tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
            tex.build_mipmaps()
        elif nearest:
            tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        else:
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        if not nearest:
            try:
                tex.anisotropy = 8.0
            except Exception:
                pass
        self.textures[key] = tex
        self.drop_bakes(key)
        self.relayer_sheets(key)      # the new picture may need a new layer
        return tex

    def drop_bakes(self, key):
        """Forget sheets baked from this one; the source changed."""
        mark = f"{key}@"
        for name in [k for k in self.textures if str(k).startswith(mark)]:
            tex = self.textures.pop(name)
            self.tile.pop(name, None)
            tex.release()

    def shader_pass(self, value):
        """A shader name, class or pass, resolved or None."""
        if value is None or isinstance(value, shadermod.ShaderPass):
            return value
        if isinstance(value, type) and issubclass(value, shadermod.Shader):
            return shadermod.make_pass(value)
        project = getattr(self, "project", None)
        name = str(value)
        find = getattr(project, "shader_class", None)
        cls = find(name) if find is not None else None
        if cls is None:
            shadermod.warn_once(f"no shader named {name!r} in this project")
            return None
        return shadermod.make_pass(cls)

    def build_shader_program(self, pas):
        """This renderer's GL program for one shader pass, or None."""
        self._bind()
        vs = VS if pas.mode == "uv" else VS_BLIT
        try:
            prog = self.ctx.program(vertex_shader=vs,
                                    fragment_shader=pas.source)
        except Exception as exc:
            if not pas.error:
                pas.error = str(exc)
                shadermod.report(f"{pas.name}: {exc}", "error")
            return None
        self._shader_progs.append(prog)
        if pas.mode != "uv":
            write_uniform(prog, "u_box", (0.0, 0.0, 1.0, 1.0))
            self._shader_quads[id(prog)] = self.ctx.vertex_array(
                prog, [(self.quad_vbo, "2f", "in_pos")], self.quad_ibo)
        write_uniform(prog, "u_tex", 0)
        shadermod.report(f"{pas.name}: compiled as a {pas.mode} shader, "
                         f"{len(pas.source.splitlines())} lines")
        return prog

    def _shader_uniforms(self, prog, pas, tex=None, size=None, mesh=False):
        """Point one pass at its picture, clock and knobs."""
        w, h = size or self.target
        write_uniform(prog, "u_size", (float(w), float(h)))
        write_uniform(prog, "u_time", float(self.time))
        write_uniform(prog, "u_seed", float(self._post_frame % 991))
        if mesh:
            # mesh passes wear the world camera; frame passes do not
            write_uniform(prog, "u_mvp", self._mvp)
            write_uniform(prog, "u_eye", self._eye)
        for name in pas.knob_types:
            write_uniform(prog, f"k_{name}", pas.values.get(name, 0.0))
        if tex is not None:
            tex.use()

    def shaded_texture(self, sheet, shader):
        """The sheet once through a `texture` shader."""
        self._bind()
        pas = self.shader_pass(shader)
        base = self.color_texture(sheet)
        if pas is None or pas.mode != "texture":
            return base
        key = f"{base}@{pas.name}"
        if key in self.textures:
            return key
        src = self.textures.get(base)
        prog = pas.program(self)
        if src is None or prog is None:
            return base
        w, h = src.size
        out = self.ctx.texture((w, h), src.components)
        out.filter = src.filter
        out.repeat_x = src.repeat_x
        out.repeat_y = src.repeat_y
        fbo = self.ctx.framebuffer(color_attachments=[out])
        ctx = self.ctx
        self._post_frame += 1
        try:
            fbo.use()
            ctx.viewport = (0, 0, w, h)
            ctx.scissor = None
            ctx.disable(moderngl.DEPTH_TEST)
            ctx.disable(moderngl.BLEND)
            self._shader_uniforms(prog, pas, src, size=(w, h))
            self._shader_quads[id(prog)].render()
        finally:
            fbo.release()
            ctx.enable(moderngl.DEPTH_TEST)
        self.textures[key] = out
        self.tile[key] = self.tile.get(base, 0.0)
        self.holes[key] = self.holes.get(base, False)
        return key

    def has_texture(self, key):
        return key in self.textures

    def bake_lightmap(self, name, md, ambient, lights, size=None):
        """Freeze a model's surface light into a lightmap."""
        if md is None or not getattr(md, "idx", None) or not md.pos:
            return None
        self._bind()
        ctx = self.ctx
        prog = self.prog_bake
        size = int(max(16, size or DEFAULT_LM_SIZE))
        chosen = [L for L in lights
                  if getattr(L, "enabled", True) and L.level() > 0.0]
        chosen = chosen[:MAX_LIGHTS]
        lp = np.zeros((MAX_LIGHTS, 3), np.float32)
        lc = np.zeros((MAX_LIGHTS, 3), np.float32)
        ld = np.zeros((MAX_LIGHTS, 3), np.float32)
        lsh = np.zeros((MAX_LIGHTS, 4), np.float32)
        lat = np.zeros((MAX_LIGHTS, 4), np.float32)
        for i, L in enumerate(chosen):
            pos, col, dirv, shape, atten = L.gpu()
            lp[i] = list(pos) + [0.0] * (3 - len(pos))
            lc[i] = col
            ld[i] = dirv
            lsh[i] = shape
            lat[i] = atten
        prog["u_amb"].write(np.asarray(ambient, np.float32))
        prog["u_light_pos"].write(lp)
        prog["u_light_col"].write(lc)
        prog["u_light_dir"].write(ld)
        prog["u_light_shape"].write(lsh)
        prog["u_light_atten"].write(lat)
        prog["u_light_n"].value = len(chosen)
        self._bind_cookie(prog, chosen)
        acc = _Accum()
        acc.append(md, opacity=None)
        vbo = ctx.buffer(acc.interleaved().tobytes())
        ibo = ctx.buffer(np.ascontiguousarray(acc.idx, np.uint32).tobytes())
        out = ctx.texture((size, size), 3)
        out.filter = (moderngl.LINEAR, moderngl.LINEAR)
        fbo = ctx.framebuffer(color_attachments=[out])
        vao = ctx.vertex_array(
            prog,
            [(vbo, "3f 3f 2f 2f 4f",
              "in_pos", "in_nrm", "in_uv", "in_uv2", "in_col")],
            ibo, skip_errors=True)
        buf = bytearray(size * size * 3)
        try:
            fbo.use()
            ctx.viewport = (0, 0, size, size)
            ctx.scissor = None
            ctx.disable(moderngl.DEPTH_TEST)
            ctx.disable(moderngl.CULL_FACE)
            ctx.disable(moderngl.BLEND)
            ctx.clear(0.0, 0.0, 0.0)
            vao.render(moderngl.TRIANGLES)
            fbo.read_into(buf, viewport=(0, 0, size, size), components=3)
        finally:
            for obj in (vao, vbo, ibo, fbo, out):
                obj.release()
            ctx.enable(moderngl.DEPTH_TEST)
            ctx.enable(moderngl.CULL_FACE)
        # bytes already sit in texture order, so no flip
        key = f"{name}@lm"
        if key in self.textures:
            self.textures[key].release()
        tex = ctx.texture((size, size), 3, bytes(buf))
        tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        tex.build_mipmaps()
        tex.repeat_x = tex.repeat_y = False
        self.textures[key] = tex
        self.tile[key] = 0.0
        self.baked_lights = True
        return key

    def read_texture_rgb(self, key):
        """A cached texture's bytes, in image order."""
        self._bind()
        tex = self.textures.get(key)
        if tex is None or tex.components < 3:
            return None
        w, h = tex.size
        data = tex.read(level=0)
        arr = np.frombuffer(data, np.uint8).reshape(h, w, tex.components)
        return np.ascontiguousarray(np.flipud(arr[..., :3]))

    def tile_for(self, key, blend="opaque"):
        """Metres one sheet repeat covers; 0 if none."""
        if blend not in LIT_BLENDS:
            return 0.0
        return float(self.tile.get(key, 0.0) or 0.0)

    def uv_for(self, key, blend="opaque", uv=None, anchor=None):
        """The uv fit a mesh draws with: its own, else the sheet's tile."""
        if uv:
            return uv if len(uv) == 5 else tuple(uv) + (anchor,)
        tile = self.tile_for(key, blend)
        return (tile, (1.0, 1.0), (0.0, 0.0), 0.0, anchor) if tile else None

    @staticmethod
    def opacity_of(value):
        """An opacity claim as 0..1; unset means solid."""
        if value is None:
            return 1.0
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def blend_for(blend, opacity=1.0, holes=False):
        """The layer a thing of this opacity really draws in."""
        solid = Renderer.opacity_of(opacity) >= 1.0
        if blend == "opaque" and (not solid or holes):
            return "trans"
        if blend == "trans" and solid and not holes:
            return "opaque"
        return blend

    def has_holes(self, key):
        """Does this sheet have pixels the world shows through?"""
        return bool(self.holes.get(key))

    def layer_for(self, blend, opacity=1.0, key=None):
        """The layer a thing draws in, its picture asked as well as its own.

        A cut-out is not solid however solid its opacity claims: the opaque
        batch is drawn with blending off, so its blank pixels would paint
        out whatever is behind them. Anything with holes joins the blended
        `trans` layer, where its edges mix with the world instead.
        """
        return self.blend_for(blend, opacity, self.has_holes(key))

    def relayer_sheets(self, key):
        """Every live mesh wearing one sheet, re-sorted by what it now shows."""
        for d in self.dynamics:
            if d._texture == key:
                d.relayer()

    def write_texture(self, key, arr):
        """Update texture pixels, in place when the shape matches."""
        self._bind()
        rgba = arr.ndim == 3 and arr.shape[2] == 4
        data = np.ascontiguousarray(np.flipud(arr), dtype=np.uint8)
        h, w = data.shape[:2]
        comp = 4 if rgba else 3
        tex = self.textures.get(key)
        if tex is not None and tuple(tex.size) == (w, h) \
                and tex.components == comp:
            tex.write(data.tobytes())
            # a painted sheet can gain or lose its holes between frames
            was = self.holes.get(key)
            self.holes[key] = rgba and bool(data[..., 3].min() < 250)
            if self.holes[key] != was:
                self.relayer_sheets(key)
            return tex
        return self.texture(key, arr, rgba=rgba, repeat=False,
                            filter="linear", mipmaps=False)

    def color_texture(self, value):
        """The texture key for `value`, registering a solid sheet first."""
        if value is None:
            return "white"
        key = colors.key(value)
        if key in self.textures:
            return key
        if colors.is_spelling(value) or str(key).lower() in colors.NAMED:
            arr = proctex.solid(colors.rgba(value))
            self.texture(key, arr, rgba=arr.shape[2] == 4, repeat=False,
                         filter="nearest", mipmaps=False)
        return key

    def resolve_texture(self, value):
        """A usable texture key, or None when unknown."""
        if value is None:
            return None
        key = self.color_texture(value)
        return key if key in self.textures else None

    def light_texture(self, light):
        """The cached falloff gradient a 2D light draws."""
        name = str(getattr(light, "shape_name", "radial"))
        if name == "world":
            return "white"
        kind = "box" if name == "rect" else ("ring" if name == "ring"
                                             else "circle")
        soft = float(getattr(light, "falloff", 0.0) or
                     getattr(light, "soft", 0.0))
        hole = round(float(getattr(light, "hole", 0.0) or 0.0), 3)
        outer = getattr(light, "outer", None) or (1.0, 1.0, 1.0)
        edge = ",".join(str(round(float(c), 2)) for c in outer)
        key = "light:{0}:{1}:{2}:{3}:{4}:{5}:{6}".format(
            kind, round(soft, 3), getattr(light, "atten", "smooth"),
            round(float(getattr(light, "exponent", 2.0)), 3),
            round(float(getattr(light, "falloff", 0.0)), 3), edge, hole)
        if key not in self._light_tex:
            arr = proctex.radial(soft=soft,
                                 mode=lightmod.atten_code(
                                     getattr(light, "atten", "smooth")),
                                 exponent=float(getattr(light, "exponent",
                                                        2.0)),
                                 outer=outer, shape=kind, hole=hole)
            self.texture(key, arr, rgba=True, mipmaps=False)
            self._light_tex[key] = True
        return key

    def add(self, data, texture="white", blend="opaque", claim=None,
            opacity=1.0, shader=None, uv=None, anchor=None):
        """Queue batched static geometry, or keep one mesh live."""
        opacity = self.opacity_of(opacity)
        texture = self.color_texture(texture)
        blend = self.layer_for(blend, opacity, texture)
        pas = self.shader_pass(shader)
        if pas is not None and pas.mode == "texture":
            texture = self.shaded_texture(texture, pas)
            pas = None
        if pas is not None and claim is None:
            shadermod.warn_once(f"{pas.name}: a uv shader needs a mesh of "
                                "its own, so this geometry is batched "
                                "without it")
            pas = None
        key = (texture, blend)
        fit = self.uv_for(key[0], blend, uv, anchor)
        if claim is not None:
            self._live_add(claim, data, key[0], blend, opacity, pas, fit)
            return
        buf = self._pending.setdefault(key, _Accum())
        buf.append(data, opacity, fit)

    def _live_add(self, claim, data, texkey, blend, opacity=1.0,
                  shader=None, uv=None):
        """One claimed mesh: made once, rewritten by every later claim."""
        self._bind()
        d = self._live.get(claim)
        if d is None:
            d = DynamicMesh(self, data, texkey, blend, opacity=opacity,
                            shader=shader, uv=uv,
                            anchor=uv[4] if uv and len(uv) == 5 else None)
            self.dynamics.append(d)
            self._live[claim] = d
            return
        # a reshape keeps the sheet pinned where the first one fixed it
        if uv and len(uv) > 4:
            uv = uv[:4]
        d.opacity = self.opacity_of(opacity)
        d._layer0 = blend
        d.relayer()
        d.uv = DynamicMesh.strip_uv(uv)
        if shader is not d.shader:
            d.set_shader(shader)
        acc = _Accum()
        acc.append(data, d.opacity,
                   self.uv_for(texkey, d.blend, uv, d.anchor))
        self._upload_dynamic(d, acc)

    def drop_live(self, obj_id=None, seq=None):
        """Free one object's claimed meshes for one build."""
        keys = [k for k in self._live
                if obj_id is None or (k[0] == obj_id and k[1] == seq)]
        for key in keys:
            d = self._live.pop(key)
            d.dispose()
            try:
                self.dynamics.remove(d)
            except ValueError:
                pass

    def build(self):
        """Merge every queued MeshData into one VAO per (tex, blend)."""
        self._bind()
        for (texkey, blend), acc in self._pending.items():
            if not acc.idx:
                continue
            if texkey not in self.textures:
                continue          # an unknown texture draws nothing
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
        self._live.clear()
        # a fresh world has no maps; bake lights are live
        self.baked_lights = False

    def dispose(self):
        global _ACTIVE
        self._bind()
        self.reset()
        if self.shared is None:
            # a shared cache belongs to the parent; do not free
            for tex in self.textures.values():
                tex.release()
            self.textures.clear()
        # the gradients themselves are cached in `textures`, under their
        # `light:` keys, so whoever owns that cache already freed them
        self._light_tex.clear()
        self.tile.clear()      # a rig's own sheet sizes, however shared
        self.holes.clear()
        self._release_light_fbo()
        for obj in self._shader_quads.values():
            obj.release()
        self._shader_quads.clear()
        for obj in self._shader_progs:
            obj.release()
        self._shader_progs.clear()
        for obj in (self.quad, self.quad_panel, self.prog,
                    self.prog_blit, self.prog_panel, self.prog_bake,
                    self.quad_vbo, self.quad_ibo):
            if obj is not None:
                obj.release()
        for att in list(self.fbo.color_attachments) + \
                [self.fbo.depth_attachment]:
            if att is not None:
                att.release()
        self.fbo.release()      # this rig's own target goes with the rig
        for _tex, fbo in self._panel.values():
            fbo.release()
        self._panel.clear()
        self._release_post_fbo()
        if self.shared is None and not self.windowed:
            # the window and shared contexts are not ours to destroy
            self.ctx.release()
        if _ACTIVE is self:
            _ACTIVE = None

    def close(self):
        """Dispose this rig, then let nothing outlive the context.

        `dispose()` deliberately spares a window's context, because the
        window owns it - but a framebuffer wrapper stays alive inside the
        context object and inside this rig, and the interpreter's final
        garbage pass frees those once `pygame.quit()` has destroyed the GL
        context they point at. A desktop driver shrugs that off, a
        software one segfaults with no Python frame to blame. So the
        framebuffers go too, and the context is released last, while a
        driver is still listening to hear "nothing of mine is live".
        """
        self.dispose()
        if self.shared is not None:
            return              # the parent's context is not ours to close
        ctx = self.ctx
        for own in (getattr(ctx, "fbo", None),
                    getattr(ctx, "_screen", None)):
            # the last two are moderngl's own handles on the window's
            # framebuffer; a driver may refuse to delete the default one,
            # which is not our problem while the context is still there
            try:
                if own is not None:
                    own.release()
            except Exception:
                continue
        try:
            ctx.release()
        except Exception:
            pass

    def _make_vao(self, acc, tex):
        ctx = self.ctx
        vbo = ctx.buffer(acc.interleaved().tobytes())
        ibo = ctx.buffer(np.ascontiguousarray(
            acc.idx, np.uint32).tobytes())
        vao = ctx.vertex_array(
            self.prog,
            [(vbo, "3f 3f 2f 2f 4f",
              "in_pos", "in_nrm", "in_uv", "in_uv2", "in_col")],
            ibo)
        return vao, len(acc.idx)

    def new_dynamic(self, data, texture="white", blend="add",
                    view_model=False, on_top=False, opacity=1.0,
                    shader=None, uv=None, anchor=None, frame=None):
        d = DynamicMesh(self, data, texture, blend, view_model, on_top,
                        opacity, shader, uv, anchor, frame)
        self.dynamics.append(d)
        return d

    def fade(self, mesh, opacity):
        """Re-composite an object's own mesh at a new opacity."""
        mesh.opacity = self.opacity_of(opacity)
        mesh.relayer()
        return mesh

    def _upload_dynamic(self, d, acc):
        """Hand a live mesh its vertices and program."""
        self._bind()
        prog = d.shader_prog or self.prog
        payload = acc.interleaved().tobytes()
        ipayload = np.ascontiguousarray(acc.idx, np.uint32).tobytes()
        if d.vao is not None and d._prog is prog \
                and len(payload) == d._vbo.size \
                and len(ipayload) == d._ibo.size:
            # same topology and program: rewrite in place
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
            prog,
            [(d._vbo, "3f 3f 2f 2f 4f",
              "in_pos", "in_nrm", "in_uv", "in_uv2", "in_col")],
            d._ibo, skip_errors=True)
        d._prog = prog
        d.count = len(acc.idx)

    def _target_size(self):
        w, h = self.size
        return (max(2, int(w * self.render_scale)),
                max(2, int(h * self.render_scale)))

    def _make_fbo(self):
        ctx = self.ctx
        self._release_light_fbo()
        self._release_post_fbo()
        self.target = self._target_size()
        # the colour attachment is a texture so both can sample
        self.color = ctx.texture(self.target, 3)
        self.color.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.depth = ctx.depth_renderbuffer(self.target)
        self.fbo = ctx.framebuffer(color_attachments=[self.color],
                                   depth_attachment=self.depth)
        self.prog_panel["u_size"].value = (float(self.target[0]),
                                           float(self.target[1]))

    def _release_post_fbo(self):
        """Drop the shader chain's two targets; they are rebuilt bigger."""
        for obj in (self.pbo, self.ptex, self.qbo, self.qtex):
            if obj is not None:
                obj.release()
        self.pbo = self.ptex = None
        self.qbo = self.qtex = None

    def _release_light_fbo(self):
        """Drop the 2D light mask; it rebuilds on resize."""
        for obj in (self.lfbo, self.ltex):
            if obj is not None:
                obj.release()
        self.lfbo = self.ltex = None

    def _light_fbo(self):
        """The light mask, made on first 2D light need."""
        if self.lfbo is None:
            self._bind()
            self.ltex = self.ctx.texture(self.target, 3)
            self.ltex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self.lfbo = self.ctx.framebuffer(color_attachments=[self.ltex])
        return self.lfbo

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
        scale = clamp_scale(scale)
        if abs(scale - self.render_scale) < 1e-4:
            return
        self.render_scale = scale
        self._bind()
        for att in list(self.fbo.color_attachments) + \
                [self.fbo.depth_attachment]:
            if att is not None:
                att.release()
        self._make_fbo()

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
            "viewport": tuple(self.viewport) if self.viewport else
                        tuple(self.target),
        }

    def set_post(self, passes):
        """Arm the frame's shader chain; return what is armed."""
        self._post = tuple(passes or ())
        return self._post

    @property
    def post(self):
        """The passes armed for the next frame, in order."""
        return self._post

    def set_clock(self, value):
        """The number `g.time` reads: the scene's clock."""
        self.time = float(value or 0.0)

    def _post_fbo(self, slot):
        """One of the chain's two full-size targets."""
        if slot == 0 and self.pbo is None:
            self.ptex = self.ctx.texture(self.target, 3)
            self.ptex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self.pbo = self.ctx.framebuffer(color_attachments=[self.ptex])
        if slot == 1 and self.qbo is None:
            self.qtex = self.ctx.texture(self.target, 3)
            self.qtex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self.qbo = self.ctx.framebuffer(color_attachments=[self.qtex])
        if slot == 0:
            return self.pbo, self.ptex
        return self.qbo, self.qtex

    def _post_pass(self):
        """Every armed shader once, ping-ponging between two targets."""
        ctx = self.ctx
        self._post_frame += 1
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.BLEND)
        ctx.viewport = (0, 0, *self.target)
        ctx.scissor = None
        tex, target, slot = self.color, self.fbo, 0
        for pas in self._post:
            prog = pas.program(self)
            if prog is None:
                continue
            fbo, out = self._post_fbo(slot)
            fbo.use()
            self._shader_uniforms(prog, pas, tex)
            self._shader_quads[id(prog)].render()
            tex, target, slot = out, fbo, 1 - slot
        ctx.enable(moderngl.DEPTH_TEST)
        return tex, target

    def composite_panel(self, src, key, shape="rect",
                        tint=(1.0, 1.0, 1.0), brightness=1.0):
        """Shape a screen's picture into its panel texture."""
        self._bind()
        tex = self.textures.get(key)
        if tex is None or tex.components != 4:
            return                  # the mask rides on alpha: needs RGBA
        held = self._panel.get(key)
        if held is not None and held[0] is not tex:
            held[1].release()       # the sheet was rebuilt behind us
            held = None
        if held is None:
            fbo = self.ctx.framebuffer(color_attachments=[tex])
            held = self._panel[key] = (tex, fbo)
        fbo = held[1]
        ctx = self.ctx
        fbo.use()
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.BLEND)
        ctx.viewport = (0, 0, *tex.size)
        ctx.scissor = None
        prog = self.prog_panel
        prog["u_size"].value = (float(tex.size[0]), float(tex.size[1]))
        prog["u_shape"].value = SHAPE_CODES.get(shape, 0)
        prog["u_tint"].value = (float(tint[0]), float(tint[1]),
                                float(tint[2]))
        prog["u_bright"].value = float(brightness)
        prog["u_has_src"].value = 1.0 if src is not None else 0.0
        (src if src is not None else self.textures["white"]).use()
        self.quad_panel.render()
        ctx.enable(moderngl.DEPTH_TEST)

    def drop_panel(self, key):
        """Forget a disposed screen's composite buffer."""
        held = self._panel.pop(key, None)
        if held is not None:
            held[1].release()

    def _rect(self, viewport=None):
        """Viewport rect in target pixels, top-left origin, clamped in."""
        tw, th = self.target
        if viewport is None:
            return (0, 0, tw, th)
        v = [float(c) for c in viewport]
        if len(v) != 4:
            raise ValueError("viewport needs (x, y, w, h)")
        if max(v) <= 1.0:
            # normalised fractions: (0, 0, .5, 1) is the left half
            return (int(v[0] * tw), int(v[1] * th),
                    max(2, int(v[2] * tw)), max(2, int(v[3] * th)))
        x, y = int(v[0]), int(v[1])
        w, h = max(2, int(v[2])), max(2, int(v[3]))
        x = max(0, min(x, tw - 2))
        y = max(0, min(y, th - 2))
        return (x, y, min(w, tw - x), min(h, th - y))

    def _matrix(self, eye, yaw, pitch, fov=DEFAULT_FOV, near=None,
                far=None, roll=0.0, size=None):
        """Projection and view matrices for one camera state."""
        w, h = size or self.target
        proj = perspective(math.radians(fov), w / h,
                           DEFAULT_NEAR if near is None else near,
                           DEFAULT_FAR if far is None else far)
        view = look_at(np.asarray(eye, np.float64), yaw, pitch, roll)
        return proj, view

    def _bind_tex(self, prog, key):
        """Point `u_tex` at a mesh's texture; False if missing."""
        tex = self.textures.get(key)
        if tex is None:
            return False
        write_uniform(prog, "u_has_tex",
                      0.0 if key == "white" else 1.0)
        tex.use()
        return True

    def _bind_lm(self, prog, key):
        """Point `u_lm` at a mesh's lightmap, or clear it."""
        tex = self.textures.get(key) if key else None
        if tex is None:
            self.textures["white"].use(2)
            write_uniform(prog, "u_has_lm", 0.0)
            return
        tex.use(2)
        write_uniform(prog, "u_has_lm", 1.0)

    def _draw_mesh(self, d, prog, prep=None):
        """Render one live mesh, through its own look."""
        p = d.shader_prog or prog
        if d.shader_prog is not None:
            self._shader_uniforms(p, d.shader, mesh=True)
        if not self._bind_tex(p, d.texture):
            return False
        self._bind_lm(p, d.lightmap)
        if prep is not None:
            prep(p)
        d.vao.render(moderngl.TRIANGLES)
        return True

    def _bind_cookie(self, prog, lights):
        """Hand the shader a 3D spot's projected pattern."""
        slot, tex = -1, None
        for i, L in enumerate(lights):
            key = getattr(L, "cookie", None)
            if not key or getattr(L, "kind", None) != lightmod.SPOT:
                continue
            got = self.textures.get(self.color_texture(key))
            if got is not None:
                slot, tex = i, got
                break
        (tex if tex is not None else self.textures["white"]).use(1)
        prog["u_has_cookie"].value = 1.0 if tex is not None else 0.0
        prog["u_cookie_slot"].value = slot

    def _has(self, kind):
        """Is there anything to draw in this blend layer?"""
        return any(b == kind and c for _v, c, _t, b in self.groups) or \
            any(d.blend == kind and d.vao is not None and d.count
                for d in self.dynamics)

    def _flat(self, prog, kind):
        """Unlit straight-alpha layers, in creation order: "alpha", "hud"."""
        ctx = self.ctx
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.CULL_FACE)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = (moderngl.SRC_ALPHA,
                          moderngl.ONE_MINUS_SRC_ALPHA)
        prog["u_mode"].value = 2.0
        for vao, count, texkey, blend in self.groups:
            if blend != kind:
                continue
            if self._bind_tex(prog, texkey):
                vao.render(moderngl.TRIANGLES)
        for d in self.dynamics:
            if d.blend != kind or d.vao is None or not d.count:
                continue
            self._draw_mesh(d, prog)

    def _blended(self, prog):
        """The two 3D layers carrying alpha: trans, panel."""
        if not (self._has("trans") or self._has("panel")):
            return
        ctx = self.ctx
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.CULL_FACE)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = (moderngl.SRC_ALPHA,
                          moderngl.ONE_MINUS_SRC_ALPHA)
        for kind, mode in (("trans", 0.0), ("panel", 2.0)):
            prog["u_mode"].value = mode
            for vao, count, texkey, blend in self.groups:
                if blend != kind:
                    continue
                if self._bind_tex(prog, texkey):
                    self._bind_lm(prog, None)
                    vao.render(moderngl.TRIANGLES)
            for d in self.dynamics:
                if d.blend != kind or d.vao is None or not d.count:
                    continue
                self._draw_mesh(d, prog)
        ctx.disable(moderngl.BLEND)
        ctx.enable(moderngl.CULL_FACE)
        prog["u_mode"].value = 0.0

    def _lit_mask(self, scene, prog, rect):
        """Fill the light mask with every 2D light's shape, additively."""
        ctx = self.ctx
        self._light_fbo().use()
        ctx.viewport = (0, 0, *self.target)
        ctx.scissor = None
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.CULL_FACE)
        ctx.enable(moderngl.BLEND)
        amb = getattr(scene, "ambient2d", None) or DEFAULT_AMBIENT2D
        # the dimmer reaches unlit corners, so a blackout is black
        master = getattr(scene, "master", 1.0)
        master = 1.0 if master is None else float(master)
        ctx.disable(moderngl.BLEND)
        ctx.clear(float(amb[0]) * master, float(amb[1]) * master,
                  float(amb[2]) * master)
        ctx.enable(moderngl.BLEND)
        prog["u_mode"].value = 3.0
        prog["u_boost"].value = 1.0
        prog["u_has_cookie"].value = 0.0
        self.textures["white"].use(1)

        def batch(keep, blend):
            ctx.blend_func = blend
            for vao, count, texkey, kind in self.groups:
                if kind != "light" or not count or not keep(1.0):
                    continue
                if self._bind_tex(prog, texkey):
                    vao.render(moderngl.TRIANGLES)
            for d in self.dynamics:
                if d.blend != "light" or d.vao is None or not d.count:
                    continue
                if not keep(float(d.boost)):
                    continue
                cookie = self.textures.get(d.cookie) if d.cookie else None

                def paint(p, boost=float(d.boost), pat=cookie):
                    write_uniform(p, "u_boost", boost)
                    if pat is not None:
                        pat.use(1)
                        write_uniform(p, "u_has_cookie", 1.0)

                if self._draw_mesh(d, prog, paint) and cookie is not None:
                    self.textures["white"].use(1)
                    prog["u_has_cookie"].value = 0.0

        # a light's energy rides `u_boost`; a spent light draws nothing
        batch(lambda boost: boost > 0.0, moderngl.ADDITIVE_BLENDING)
        batch(lambda boost: boost < 0.0,
              (moderngl.ZERO, moderngl.SRC_COLOR))
        prog["u_mode"].value = 0.0
        prog["u_boost"].value = 1.0
        ctx.blend_func = moderngl.ADDITIVE_BLENDING

    def _composite_mask(self, rect):
        """Multiply the mask over the region just drawn."""
        ctx = self.ctx
        x, gl_y, w, h = rect
        tw, th = self.target
        self.fbo.use()
        ctx.viewport = (x, gl_y, w, h)
        ctx.scissor = (x, gl_y, w, h)
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.CULL_FACE)
        ctx.enable(moderngl.BLEND)
        # DST_COLOR x SRC multiplies the mask over the frame
        ctx.blend_func = (moderngl.DST_COLOR, moderngl.ZERO)
        box = (x / tw, gl_y / th, (x + w) / tw, (gl_y + h) / th)
        self.prog_blit["u_box"].value = box
        self.prog_blit["u_tex"].value = 0
        self.ltex.use()
        self.quad.render()

    def _pick_lights(self, scene, eye):
        """The 3D lights filling the shader's eight slots."""
        got = []
        for entry in getattr(scene, "lights", ()) or ():
            L = entry if isinstance(entry, lightmod.Light) else \
                lightmod.coerce(entry, scene)
            if not getattr(L, "gpu_slots", True):
                continue
            if not getattr(L, "enabled", True) or L.level() <= 0.0:
                continue
            if self.baked_lights and getattr(L, "bake", False):
                # already baked, so it must not be lit live
                continue
            got.append(L)
        if len(got) > MAX_LIGHTS:
            got.sort(key=lambda L: (-float(getattr(L, "priority", 0.0)),
                                    L.distance_to(eye)))
            got = got[:MAX_LIGHTS]
        return got

    def render(self, eye, yaw=None, pitch=None, scene=None, *, fov=None,
               near=None, far=None, roll=None, viewport=None):
        """Draw `scene` from a camera and hand back a Surface."""
        camera = None
        if pitch is None and scene is None and yaw is not None:
            # `render(camera, scene)`: the camera owns the whole frustum
            camera, scene = eye, yaw
            eye = camera.view_eye() if hasattr(camera, "view_eye") \
                else list(camera.eye)
            yaw = camera.view_yaw() if hasattr(camera, "view_yaw") \
                else camera.yaw
            pitch = camera.view_pitch() if hasattr(camera, "view_pitch") \
                else camera.pitch
            if fov is None:
                fov = getattr(camera, "fov", None)
            if near is None:
                near = getattr(camera, "near", None)
            if far is None:
                far = getattr(camera, "far", None)
            if roll is None:
                roll = (camera.view_roll() if hasattr(camera, "view_roll")
                        else getattr(camera, "roll", 0.0))
            if viewport is None:
                viewport = getattr(camera, "viewport", None)
        ctx = self.ctx
        self._bind()
        self.fbo.use()
        x, y, w, h = self._rect(viewport)
        self.viewport = (x, y, w, h)
        self.camera = camera            # what the last frame looked through
        # GL counts from the bottom left, the api from top
        gl_y = self.target[1] - y - h
        ctx.viewport = (x, gl_y, w, h)
        ctx.scissor = (x, gl_y, w, h)
        cc = getattr(scene, "clear_color", (0.02, 0.02, 0.03))
        ctx.clear(cc[0], cc[1], cc[2], 1.0)
        ctx.enable(moderngl.DEPTH_TEST)

        fov = float(fov if fov is not None else
                    getattr(scene, "fov", DEFAULT_FOV))
        near = float(near if near is not None else
                     getattr(scene, "near", DEFAULT_NEAR))
        far = float(far if far is not None else
                    getattr(scene, "far", DEFAULT_FAR))
        roll = float(roll if roll is not None else
                     getattr(scene, "roll", 0.0))
        ortho = getattr(camera, "projection", "perspective") == "ortho"
        if ortho:
            # 2D/UI: flat world-pixel space, ortho projection only
            proj = orthographic(*camera.ortho_box())
            view = np.eye(4, dtype=np.float32)
        else:
            proj, view = self._matrix(eye, yaw, pitch, fov, near, far, roll,
                                      (w, h))
        mvp = np.ascontiguousarray((proj @ view).T, dtype=np.float32)
        prog = self.prog
        # a mesh wearing its own program needs this frame's camera
        self._mvp = mvp
        self._eye = np.asarray(eye, np.float32)
        prog["u_mvp"].write(mvp)
        prog["u_eye"].write(self._eye)
        # the master dimmer scales the floor too
        master = getattr(scene, "master", 1.0)
        master = 1.0 if master is None else float(master)
        prog["u_amb"].write(np.asarray(
            [c * master for c in getattr(scene, "ambient",
                                         (0.2, 0.2, 0.2))], np.float32))
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

        # upload the lights that matter; the rest fade out
        lights = self._pick_lights(scene, eye)
        lp = np.zeros((MAX_LIGHTS, 3), np.float32)
        lc = np.zeros((MAX_LIGHTS, 3), np.float32)
        ld = np.zeros((MAX_LIGHTS, 3), np.float32)
        lsh = np.zeros((MAX_LIGHTS, 4), np.float32)
        lat = np.zeros((MAX_LIGHTS, 4), np.float32)
        for i, L in enumerate(lights):
            pos, col, dirv, shape, atten = L.gpu()
            lp[i] = list(pos) + [0.0] * (3 - len(pos))
            lc[i] = col
            ld[i] = dirv
            lsh[i] = shape
            lat[i] = atten
        prog["u_light_pos"].write(lp)
        prog["u_light_col"].write(lc)
        prog["u_light_dir"].write(ld)
        prog["u_light_shape"].write(lsh)
        prog["u_light_atten"].write(lat)
        prog["u_light_n"].value = len(lights)
        self._bind_cookie(prog, lights)

        # lit, depth-sorted opaque batch
        ctx.enable(moderngl.CULL_FACE)
        ctx.disable(moderngl.BLEND)
        prog["u_mode"].value = 0.0
        for vao, count, texkey, blend in self.groups:
            if blend != "opaque":
                continue
            if self._bind_tex(prog, texkey):
                self._bind_lm(prog, None)   # a merged batch shares no map
                vao.render(moderngl.TRIANGLES)
        # reshaped-per-frame lit geometry (world-space)
        for d in self.dynamics:
            if d.blend != "opaque" or d.view_model \
                    or d.vao is None or not d.count:
                continue
            self._draw_mesh(d, prog)
        # view models live in camera space: proj-only, two-sided
        vms = [d for d in self.dynamics
               if d.blend == "opaque" and d.view_model
               and d.vao is not None and d.count]
        if vms:
            m = view[:3, :3]
            vm = np.ascontiguousarray(proj.T, np.float32)
            prog["u_mvp"].write(vm)
            prog["u_eye"].write(np.zeros(3, np.float32))
            self._mvp = vm
            self._eye = np.zeros(3, np.float32)
            prog["u_sun_dir"].write(np.asarray(m @ sdv, np.float32))
            prog["u_light_pos"].write(
                np.asarray((lp - np.asarray(eye, np.float32)) @ m.T,
                           np.float32))
            # cone and tube directions rotate into camera space too
            prog["u_light_dir"].write(np.asarray(ld @ m.T, np.float32))
            ctx.disable(moderngl.CULL_FACE)
            for d in vms:
                if d.on_top:
                    continue
                self._draw_mesh(d, prog)
            # on-top view models: no depth test, still writing depth
            if any(d.on_top for d in vms):
                ctx.disable(moderngl.DEPTH_TEST)
                for d in vms:
                    if not d.on_top:
                        continue
                    self._draw_mesh(d, prog)
                ctx.enable(moderngl.DEPTH_TEST)
            ctx.enable(moderngl.CULL_FACE)
            # put the world uniforms back for the additive pass
            self._mvp = mvp
            self._eye = np.asarray(eye, np.float32)
            prog["u_mvp"].write(mvp)
            prog["u_eye"].write(np.asarray(eye, np.float32))
            prog["u_sun_dir"].write(np.asarray(sdv, np.float32))
            prog["u_light_pos"].write(lp)
            prog["u_light_dir"].write(ld)

        # glows: additive, two-sided, after every opaque surface
        self._blended(prog)
        ctx.disable(moderngl.CULL_FACE)
        ctx.enable(moderngl.BLEND)
        # ADDITIVE_BLENDING is (ONE, ONE); shader premultiplies glow
        ctx.blend_func = moderngl.ADDITIVE_BLENDING
        prog["u_mode"].value = 1.0
        for vao, count, texkey, blend in self.groups:
            if blend != "add":
                continue
            prog["u_has_tex"].value = 1.0
            self.textures[texkey].use()
            vao.render(moderngl.TRIANGLES)
        for d in self.dynamics:
            if d.blend != "add" or d.vao is None or not d.count:
                continue
            self._draw_mesh(d, prog)

        # 2D world: unlit straight-alpha quads, back to front
        if self._has("alpha"):
            self._flat(prog, "alpha")

        # 2D lighting: mask, multiply, then HUD stays undimmed
        if self._has("light"):
            self._lit_mask(scene, prog, (x, gl_y, w, h))
            self._composite_mask((x, gl_y, w, h))

        if self._has("hud"):
            self._flat(prog, "hud")

        ctx.disable(moderngl.BLEND)
        ctx.viewport = (0, 0, *self.target)
        ctx.scissor = None
        ctx.enable(moderngl.DEPTH_TEST)

        src = self.fbo
        self.last_out = self.color
        if self._post:
            # the chain's last scratch holds the finished picture
            self.last_out, src = self._post_pass()
        if self.gpu_only:
            # the outer rig samples `last_out` where it lies
            return None
        data = self._read_pixels((x, gl_y, w, h), src)
        arr = np.frombuffer(data, np.uint8).reshape(h, w, 3)
        # RGB, not RGBA, so stale screen pixels never blend
        frame = np.ascontiguousarray(arr[::-1])
        # the pixels the Surface is built from, for HUD reads
        self.frame_array = frame
        return pygame.image.frombuffer(frame, (w, h), "RGB")

    def _read_pixels(self, rect, src=None):
        """A frame buffer's bytes, into one buffer kept between frames."""
        x, y, w, h = rect
        if self._read_key != (w, h):
            self._read_buf = bytearray(w * h * 3)
            self._read_key = (w, h)
        (self.fbo if src is None else src).read_into(
            self._read_buf, viewport=(x, y, w, h), components=3)
        return self._read_buf


class _Accum:
    """Merge-friendly pile of MeshData with flat list storage."""

    def __init__(self):
        self.pos = []
        self.nrm = []
        self.uv = []
        self.uv2 = []
        self.col = []
        self.idx = []

    def append(self, m, opacity=1.0, uv=None):
        base = len(self.pos)
        if uv:
            # a twin carrying new uvs, possibly the owner's own soup
            m = meshes.uv_fit(m, *uv)
        self.pos.extend(m.pos)
        self.nrm.extend(m.nrm)
        self.uv.extend(m.uv)
        # uv2 falls back to albedo uv; `u_has_lm` stays 0
        self.uv2.extend(m.uv2 if len(m.uv2) == len(m.pos) else m.uv)
        if opacity is not None and opacity < 1.0:
            self.col.extend([c[:3] + (c[3] * opacity,) for c in m.col])
        else:
            self.col.extend(m.col)
        self.idx.extend([i + base for i in m.idx])

    def interleaved(self):
        n = len(self.pos)
        out = np.empty((n, 14), np.float32)
        out[:, 0:3] = self.pos
        out[:, 3:6] = self.nrm
        out[:, 6:8] = self.uv
        out[:, 8:10] = self.uv2
        out[:, 10:14] = self.col
        return out
