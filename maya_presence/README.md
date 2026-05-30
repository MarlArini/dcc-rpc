## Installation Instructions
TODO

## Accessing Settings
TODO

## Settings & Features
#### State and Details allow you to choose from:
        ("Scene name", "scene"),
        ("Mesh count", "mesh"),
        ("Poly count", "poly"),
        ("Joint count", "joint"),
        ("Light count", "light"),
        ("Camera count", "cam"),
        ("Blendshape count", "blendshape"),
        ("Material count", "mat"),
        ("Texture count", "tex"),
        ("File size", "size"),
        ("Current frame", "frame"),
        ("Active object", "active"),
        ("Current tool context", "context")
- Scene name: The names of the current project and scene, separated with a "|", e.g., "Current Project | Current Scene.mb". TODO details
- Mesh count: the number of meshes in the scene
- Poly count: the number of faces and verts in the scene. If you have the HUD element for polygon information enabled, these counts will include viewport smoothing; if not, they will be unsmoothed values.
- Joint count: the number of joints in the scene.
- Light count: the number of lights in the scene.
- Camera count: the number of camera objects in the scene, excluding the default perspective and orthographic cameras.
- Blendshape count: the number of blendshapes in the scene.
- Material count: the number of materials in the scene.
- Texture count: the number of textures in the scene.
- File size: the size of the scene file on disk.
- Current frame: the currently selected frame.
- Active object: the object currently selected
- Current tool context: the context name of the current tool, e.g., "PolyCut"

#### Render Engine Plugins
- For light, material, and texture count, render engines such as Arnold or Redshift add custom types which will not be picked up by a simple search for objects of the default 'light' type category in Maya. A global setting exists for each engine to decide whether to count its resources in each of those categories, along with default Maya resources. Currently supported are Arnold, Redshift, V-Ray, and RenderMan.

#### Rendering
When rendering, if render details are enabled, render information will override the details field with information about the render: the scene name, resolution, fps, and frame range, formatted as "Rendering {scene name}: {width}x{height}, Frame {frame} of {range} @ {fps}"
TODO brevity
Additionally, if render details are enabled, small icons are enabled, and the render engine is a supported extension (Arnold, Redshift, V-Ray, RenderMan), the render engine will be displayed as the small icon.

#### Icons
If you enable small icons, besides the rendering icons, there are icons for the workspace or context you are in. 
The first check will be workspace: if you are in the Modeling workspace you will get a modeling icon, Animation will get an animation icon, etc.
If you are in the 'General' workspace, the current tool context will be evaluated. For a subset of the contexts, an icon has been selected; others (e.g., selection) are not specific to a particular task and will not get an icon.