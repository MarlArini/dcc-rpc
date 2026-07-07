## Installation Instructions
- Download and extract the MayaPresence ZIP from releases, or clone the repository and copy the maya_presence folder; place the maya_presence folder somewhere permanent. Assume the full path to the folder location looks something like C:/.../maya_presence
- Add that location to your Maya.env file under C:/Users/YourName/Documents/maya/YEAR/Maya.env (create it if it does not exist) by adding a new line "MAYA_MODULE_PATH=;C:/.../maya_presence"
- Restart Maya if it was already running
- Open Maya and go to Windows -> Settings/Preferences -> Plug-In Manager. There should be a new tab "C:/.../maya_presence"; check the "Loaded" and "Auto load" boxes to enable the plugin in the current session and on startup.

## Accessing Settings
Under "Windows" in the top toolbar, a new option will be added at the bottom of the menu: "Maya Presence Settings...". Click to open the GUI settings menu.

## Settings & Features
#### State and Details allow you to choose from:
- **Scene name**: The names of the current project and scene, separated with a "|", e.g., "Current Project | Current Scene.mb".
- **Mesh count**: the number of meshes in the scene
- **Poly count**: the number of faces and verts in the scene. If you have the HUD element for polygon information enabled, these counts will include viewport smoothing; if not, they will be unsmoothed values.
- **Joint count**: the number of joints in the scene.
- **Light count**: the number of lights in the scene.
- **Camera count**: the number of camera objects in the scene, excluding the default perspective and orthographic cameras.
- **Blendshape count**: the number of blendshapes in the scene.
- **Material count**: the number of materials in the scene.
- **Texture count**: the number of textures in the scene.
- **File size**: the size of the scene file on disk.
- **Current frame**: the currently selected frame.
- **Active object**: the object currently selected
- **Current tool context**: the context name of the current tool, e.g., "PolyCut"

#### Render Engine Plugins
- For light, material, and texture count, third-party render engines add custom types which will not be picked up by a simple search for objects of the default 'light' type category in Maya. A global setting exists for each engine to decide whether to count its resources in each of those categories, along with default Maya resources. This may increase the time required for an RPC update since it runs a more complex search through the scene graph.

#### Rendering
When rendering, if render details are enabled, render information will override the details field with information about the render: the scene name, resolution, and frames rendered, formatted as "Rendering {scene name}: {width}x{height}, Frame {frame}"
Additionally, if render details and small icons are enabled and the render engine is a supported extension (Arnold, Redshift, V-Ray, RenderMan), the render engine will be displayed as the small icon.

#### Icons
If you enable small icons, besides the rendering icons, there are icons for the workspace or context you are in. 
The first check will be workspace: if you are in the Modeling workspace you will get a modeling icon, Animation will get an animation icon, etc.
If you are in the 'General' workspace, the current tool context will be evaluated. For a subset of the contexts, an icon has been selected; others (e.g., selection) are not specific to a particular task and will not get an icon.