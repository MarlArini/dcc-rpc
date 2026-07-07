## DCC-RPC
Discord Rich Presence integrations for a number of creative applications. Currently supported: Krita, GIMP, Autodesk Maya, Foundry Nuke, Cinema 4D, Adobe Substance 3D Painter, and Adobe Substance 3D Designer.

## Common Functionality
All plugins share a basic design pattern. There are several different pieces of information they can surface, specific to the application and context you're in (e.g., number of meshes in a modeling application like Maya, or number of nodes in a node-based editor like Designer). You can choose which information is displayed in the details field and the state field of the Rich Presence visual, or allow one or both of those fields to cycle between different values. The default is for each application to show the name of the project/file you're currently working on in the details field, and to show some fixed app-specific piece of information (layer name, poly count, etc.) in the state field.

All apps also allow up to two customizable buttons to link to personal sites or portfolios.

Some apps will show additional information using the small icon feature, for example, the tool you're using in Krita, or the render engine you're using in Maya. This can be disabled if not desired. For Krita, Substance Painter, and GIMP the icon will also change color according to the current foreground color in the application. With Krita and Painter this happens only when a paint tool is selected; in GIMP it is always displayed, since the GIMP API does not allow querying the active tool.

All apps have a GUI settings menu which allows you to interactively edit your settings from within the application.

It is recommended that you look at the README for each specific plugin you plan to use, *especially* for GIMP, which has more limitations than the other plugins. For GIMP, it is difficult or impossible on some platforms to determine the active image; you will want to read through what fallback options are available. 

## Unsupported Apps
#### Made by others
Blender already has an excellent RPC plugin which inspired this project: https://github.com/abrasic/blendpresence.

Many of Adobe's Creative Cloud applications, such as Photoshop and After Effects, are supported by https://github.com/teeteeteeteetee/adobe-discord-rpc.

The Unreal Editor has a plugin (Windows-only) through itch.io: https://dn2.itch.io/editor-discord-rich-presence.

#### Low Prospective Audience
Mari and Katana are not supported: non-commercial Mari users cannot use Python scripting, and Katana has no non-commercial version.

DaVinci Resolve has a scripting API, but non-Studio users can only execute commands from inside the application console; external file scripts will not execute.

#### Currently Impossible
ZBrush does not have support in the API for the concept of long-running/threaded plugins; plugins are invoked from the scripting menu and expected to run on the main thread and return, blocking the application until they do so. If the API expands, I will look into creating a plugin.

Marvelous Designer also lacks threading support.

Clip Studio Paint does not have a plugin system at all, at least within the United States. There is a C++ SDK for the Japanese version of the program; if this ever expands internationally, I'll consider writing a plugin.

## Bug Reports
If you're having a problem, open an issue and note the application, application version, and plugin version, as well as the tested application version mentioned in the plugin README. If your application version is older than the tested version, e.g., the plugin says it was tested on Nuke 17 and it is not working on Nuke 16, add the "Backwards Compatibility" tag when opening the issue. These issues will likely be lower priority than issues on supported versions, and in some cases may not be addressed at all: if the application version is so old it is using Python 2 instead of Python 3, I will not be rewriting the code to be Python 2 compliant. For most applications the Python executable should be bundled with the installation somewhere; if you can find it and check its version before creating the issue, please don't open an issue if you know it's Python 2.