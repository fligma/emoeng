"""GL-presented window: the frame reaches the screen by swapping, not"""

import moderngl
import numpy as np
import pygame

from .renderer import FS_BLIT

# the layer is top-down; one shader mirrors it, no flip
VS_LAYER = """#version 330
in vec2 in_pos;
out vec2 v_uv;
void main() {
    v_uv = vec2(in_pos.x, 1.0 - in_pos.y);
    gl_Position = vec4(in_pos * 2.0 - 1.0, 0.0, 1.0);
}
"""


class GLWindow:
    """Presents a renderer's graded frame to the window, with the"""

    def __init__(self, renderer):
        self.r = renderer
        renderer._bind()
        self.ctx = renderer.ctx
        # framebuffer 0 is the drawable; binding it wraps a handle
        self.window_fbo = self.ctx.detect_framebuffer(0)
        self.size = (max(2, int(renderer.size[0])),
                     max(2, int(renderer.size[1])))
        self.prog_layer = self.ctx.program(vertex_shader=VS_LAYER,
                                           fragment_shader=FS_BLIT)
        self.prog_layer["u_tex"].value = 0
        self.quad_layer = self.ctx.vertex_array(
            self.prog_layer, [(renderer.quad_vbo, "2f", "in_pos")],
            renderer.quad_ibo)
        self.layer = self._make_layer()

    def _make_layer(self):
        tex = self.ctx.texture(self.size, 4)
        tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        return tex

    def resize(self, size):
        """Follow the window; the caller swaps the layer surface."""
        size = (max(2, int(size[0])), max(2, int(size[1])))
        if size == self.size:
            return
        self.layer.release()
        self.size = size
        self.layer = self._make_layer()

    def present(self, frame, box=(0.0, 0.0, 1.0, 1.0), layer=None,
                clear=(0.02, 0.02, 0.03)):
        """Two quads to the back buffer and nothing else."""
        r = self.r
        r._bind()
        ctx = self.ctx
        self.window_fbo.use()         # the render left its own fbo bound
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.CULL_FACE)
        ctx.disable(moderngl.BLEND)
        w, h = self.size
        ctx.viewport = (0, 0, w, h)
        ctx.scissor = None
        ctx.clear(float(clear[0]), float(clear[1]), float(clear[2]), 1.0)
        prog = r.prog_blit
        prog["u_tex"].value = 0
        prog["u_box"].value = tuple(box)
        frame.use()
        r.quad.render()
        if layer is not None:
            data, swizzle = self._pixels(layer)
            self.layer.write(data)
            ctx.enable(moderngl.BLEND)
            ctx.blend_func = (moderngl.SRC_ALPHA,
                              moderngl.ONE_MINUS_SRC_ALPHA)
            self.layer.swizzle = swizzle
            self.layer.use()
            self.quad_layer.render()
            ctx.disable(moderngl.BLEND)
        ctx.enable(moderngl.DEPTH_TEST)

    def _pixels(self, layer):
        """The pygame layer as GL-ready bytes, plus the swizzle."""
        w, h = self.size
        try:
            # the surface's raw buffer: no colour conversion at all
            buf = memoryview(layer.get_view("0")).cast("B")
        except (ValueError, pygame.error):
            pass
        else:
            pitch = layer.get_pitch()
            if pitch == w * 4:
                return bytes(buf), "bgra"
            out = np.frombuffer(buf, np.uint8).reshape(
                h, pitch // 4, 4)[:, :w]
            return np.ascontiguousarray(out).tobytes(), "bgra"
        # a surface pygame will not show: build RGBA top-down
        buf = np.empty((h, w, 4), np.uint8)
        try:
            rgb = pygame.surfarray.pixels3d(layer)
            alpha = pygame.surfarray.pixels_alpha(layer)
            buf[:, :, :3] = rgb.transpose(1, 0, 2)
            buf[:, :, 3] = alpha.transpose(1, 0)
        except Exception:
            buf[:, :, :3] = pygame.surfarray.array3d(
                layer).transpose(1, 0, 2)
            buf[:, :, 3] = pygame.surfarray.array_alpha(
                layer).transpose(1, 0)
        return np.ascontiguousarray(buf).tobytes(), "rgba"

    def capture(self):
        """The window's last presented frame as an RGB Surface."""
        self.r._bind()
        w, h = self.size
        data = self.window_fbo.read(viewport=(0, 0, w, h), components=3)
        arr = np.frombuffer(data, np.uint8).reshape(h, w, 3)
        return pygame.image.frombuffer(
            np.ascontiguousarray(arr[::-1]), (w, h), "RGB")

    def dispose(self):
        self.r._bind()
        self.quad_layer.release()
        self.prog_layer.release()
        self.layer.release()
        self.layer = None
