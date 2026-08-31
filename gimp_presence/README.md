## What It Looks Like
![GIMP Rich Presence status](https://raw.githubusercontent.com/MarlArini/dcc-rpc/main/readme_images/gimp.png)

## Installation Instructions
- Download the ZIP from releases
- Open GIMP and go to Edit -> Preferences -> Folders -> Plug-Ins to find your plug-ins folder
- Extract the ZIP into that folder (the contents should end up at `<plug-ins>/gimp_presence/gimp_presence.py`)
- Restart GIMP
- The plugin starts automatically; check Filters -> Discord Presence to confirm the menu is present

## Accessing Settings
A new 'Discord Presence' submenu will be added under Filters. From it you can open the GUI settings menu and pin or unpin an image (see "Pinning the Active Image" below).

## Settings & Features
#### State and Details allow you to choose from:
- **Active image name**: the active image's filename, e.g. *'sketch.xcf'*. If no images are open, *'No images open'* is displayed. If multiple images are open and the plugin can't determine which one is active, behavior depends on your "use fallback info" setting (see "When the active image can't be determined" below).
- **Number of images**: the number of images currently open, formatted as *'__ image[s] open'*.
- **Active layer**: the name of the active layer, plus its blend mode if not 'Normal'. If the layer name contains 'layer' (e.g. *'Layer 2'*), only the name is shown; otherwise it's prefixed with 'Layer: ' (e.g. *'Layer: Highlights'*). Multiple selected layers are shown as a count, e.g. *'3 layers selected'*.
- **Number of layers**: the number of layers in the active image, with the visible count in parentheses, e.g. *'12 layers (8 visible)'*.
- **Brush preset**: the active brush name and hardness, formatted as *'Brush: __ (Hardness __)'*. GIMP's four default hardness brushes ('2. Hardness 025'/'050'/'075'/'100') are normalized to *'Brush 2'* for cleaner display.
- **Color profile**: the active image's color model and effective color profile, e.g. *'RGB (sRGB built-in)'*.
- **Image dimensions**: the active image's dimensions in pixels and resolution in PPI, e.g. *'2000x2000 @ 300ppi'*. If x- and y-PPI differ they're both shown, e.g. *'2000x2000 @ 300ppi x, 250ppi y'*.
- **Paint mode**: the active paint mode (blend mode for the current brush stroke), formatted as *'Paint mode: __'*.

#### Icons
If you enable small icons, the GIMP Paint Brush icon will be displayed as a small icon. GIMP provides no option to query the active tool, so the specific tool you are using cannot be determined by the plugin.

If you additionally enable colored icons, the small icon will be a colored version of the paintbrush icon. Since the icon must be chosen from a set of <300 pre-uploaded icons, the color will not exactly match what you are painting in; however, 250 colors were selected from across perceptual color space and the closest match should be visually very close to your actual color.

Enabling colored icons will also create a tooltip on the icon with a name for the color among the 250 colors which was closest to your foreground color, as well as the hex code of your actual foreground color, e.g. *'Foreground: Imperial Purple (#602F6B)'*. The default is to use creative color names, but if you want something more functional you can turn off the 'evocative names' setting to use ISCC-NBS color names, which are a standardized set of more straightforward names such as *'Moderate Purple'*.

## Finding the Active Image

> **Quick read:** If you're on Windows and haven't changed the **Title format** under Edit -> Preferences -> Image Windows -> Title & Statusbar, this should just work. You can stop reading here.

GIMP 3's Python API does not directly expose which image is currently focused/active. If no image is pinned, the plugin runs a series of workaround detection strategies, stopping as soon as one succeeds.

#### 1. Only one image open
If there is only a single image open, that image is the active image.

#### 2. Window title query (currently only works on Windows)
If more than one image is open, the plugin tries to find the active GIMP window's title and extract the image name from it. This *should* work as long as the title format for the application hasn't been changed from the default.

This step is currently **Windows-only**:
- **macOS**: may be implemented eventually, but not currently in development; I don't have a MacOS device to develop or test on.
- **Linux**: not supported. Wayland, to my knowledge, doesn't expose window titles to non-compositor processes, and is the default on modern Linux distros such as Ubuntu 26.04. Linux users with multiple images open should rely on the fallback options below.

#### 3. Fallback ordering (optional)
If the one-image check fails and the window-title query is unavailable or doesn't match any open image, the plugin can optionally fall back to picking an image by stack position. In the settings menu, **Active-image fallback** can be set to:
- **None** (default) — don't guess; some queries will return fallback information gathered from all images, unless the 'use fallback info' setting is turned off, in which case the queries will return nothing and either display nothing (if selected manually) or be skipped (if cycling).
- **Recent / Top** — the top image in the stack, which will be the most recently opened image unless you rearrange the stack.
- **Oldest / Bottom** — the bottom image in the stack, which will be the oldest opened image unless you rearrange the stack.

> You can re-order the stack by dragging images in GIMP's Images dialog (Windows -> Dockable Dialogs -> Images).

#### 4. Pinning the active image
You can override the entire detection system by **pinning** an image. With an image open, choose Filters -> Discord Presence -> Pin Image (or assign a keyboard shortcut). While pinned, the plugin always reports info about that image regardless of focus, window title, or any fallback setting. This is also useful if you have a primary working image and several auxiliary images open (reference scraps, copy-paste sources, trimming work) and you want Discord to keep showing the primary. The pinned image will remain pinned until you unpin it (Filters -> Discord Presence -> Unpin Image), or until it is closed. If you close a pinned image without unpinning, the plugin will print a warning to the GIMP console.

The pinned image is marked with a 📌 in the active image name field in Discord.

#### 5. Cross-image fallback information
When the active image can't be determined and an info field would otherwise return nothing, by default the plugin gathers information across *all* open images instead. For example:
- **Color profile**: if all open images share the same color model and profile, it's shown unmodified. If they share a model but have different profiles, you'll see *'_ images in RGB (_ color profiles)'*. If models also differ, the set of models is listed (GIMP only has three: RGB, GRAY, and INDEXED).
- **Image dimensions**: shows the dimensions of the largest open image by area, prefixed with *'Largest open image: '*.
- **Number of layers**: shows the total layer count across all open images, with image count and visible-layer count, e.g. *'47 layers in 5 images (28 visible)'*.

Every info type has such a cross-image fallback. The intent is that even when the active image can't be detected, info options still produce something useful rather than blank. If you'd rather have nothing, disable the **Use fallback info gathered from all images** setting.

## Troubleshooting Problems
If the plugin is not working, check the GIMP console (Filters -> Script-Fu -> Console, or run GIMP from a terminal) for error messages before opening an issue. These will help diagnose problems.
