# Demo

Two rooms that wear the same clothes, built with Motion Engine:

- **Prism Hall** is a walkable 3D stone room: three arches along the back
  wall, plinths down the aisles, coloured lights in the sconces, and a
  lectern standing in the middle.
- **Echo Room** is the same room drawn flat, in 2D, with a walker you steer.

Both start **plain**. Nothing wears a shader and no picture is washed until
you ask for it, and the way you ask differs with the room - which is the
whole point of the pair.

## Prism Hall - click the lectern

Walk in with **WASD**, look with the **mouse**, run with **Shift**. The walls,
plinths and lectern stop you where they look like they would.

The screen standing on the lectern holds nine switches. Aim at one and
**click**; the click goes through the glass and lands on the picture behind
it. Each switch re-dresses exactly one thing and cycles it through the looks
that thing can wear:

| Switch | What it dresses |
| --- | --- |
| `floor` `walls` `arches` `portals` `plinths` `lectern` | one part of the room's surfaces |
| `screen` | the lectern's own picture |
| `room` | the whole frame you are looking through |
| `clear` | everything, back to plain |

The same nine switches are bound to keys **1** to **9**, so a press and a
click travel the identical road: both broadcast a named trigger, and the room
answers it. The board prints the key beside each switch and the word the room
answered below.

## Echo Room - walk onto a plate

Press **Tab** to leave the hall, **Tab** again to come back. Here **WASD**
(or the arrow keys) walk the little figure, and every switch is a plate on
the floor. Walk up to one and a dialog opens over it saying **what it
activates**, **how to pull it** - its key, or a click - and **what the room
answered last**. Stand on it and press **E**, or click the plate. Only the
plate underfoot opens its dialog.

The flat room takes no mouse inside its pictures, so its lectern holds a
readout instead of a board: two lines listing every part and the look it is
currently wearing.

## One table for both rooms

Both scenes build themselves from the same script, `scripts/scenes/dressing.py`:
the parts a room is made of, the looks each part may wear, the shader chains
each picture may run through, and the nine switches that ask for them. A part
is one live merged mesh rather than a batch of statics, so it can change its
material while you are standing in the room, and a wall of ten merged boxes
still costs a single draw call.

## Run it

From the repository root:

```powershell
python -m emoeng run emoeng\projects\demo
```

Or open the project in the editor and press **F5**.

## Screenshots

![Prism Hall, the 3D room](../../../gitassets/demo-3d.png)

![Echo Room, the 2D room](../../../gitassets/demo-2d.png)
