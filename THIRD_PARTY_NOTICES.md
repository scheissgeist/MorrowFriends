# Third-party notices

MorrowFriends depends on third-party software. Those projects retain their own
copyrights and license terms.

| Component | Purpose | License |
|---|---|---|
| CustomTkinter | Windows user interface | CC0-1.0 |
| Pillow | Image handling | HPND |
| Python (embeddable distribution, in `runtime\`) | Runs the launcher | PSF-2.0 |
| Tcl/Tk (in `runtime\`) | Windowing toolkit used by tkinter | Tcl/Tk license (BSD-style) |
| websockets | WebSocket client | BSD-3-Clause |
| pywebview | Embedded web view | BSD-3-Clause |
| pythonnet | .NET integration | MIT |
| LiveKit client/server | Voice transport | Apache-2.0 |

The Windows build also includes transitive dependencies of these components.
Their license files and package metadata are the authoritative terms.

TES3MP is not included in the MorrowFriends ZIP. The launcher downloads the
selected upstream TES3MP release directly from its official GitHub repository.
Morrowind, Tribunal, and Bloodmoon are required separately and are not
redistributed by this project.
