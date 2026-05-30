## DCC-RPC
Discord Rich Presence integrations for a number of creative applications. Currently supported: Krita, GIMP, Autodesk Maya, SideFX Houdini, Foundry Nuke, Adobe Substance Painter, and Adobe Substance Designer. Support for Cinema 4D is planned. If an app you're interested in is not in that list, check the **unsupported apps** section at the bottom; it may be listed there, either because someone else has already made a rich presence plugin, or because a plugin is impossible or impractical.

## Common Functionality
All plugins share a basic design pattern. There are several different pieces of information they can surface, specific to the application and context you're in (e.g., number of meshes in a modeling application like Maya, or number of timeline clips in an editor like Resolve). You can choose which information is displayed in the details field and the state field of the rich presence visual, or allow one or both of those fields to cycle between different values. The default is for each application to show the name of the project/file you're currently working on in the details field, and to show some fixed app-specific piece of information (layer name, poly count, etc.) in the state field.

All apps also allow up to two customizable buttons to link to personal sites or portfolios.

Some apps will show additional information using the small icon feature, for example, the tool you're using in Krita, or the render engine you're using in Maya. This can be turned off if not desired. For Krita, Substance Painter, and GIMP the icon will also change color according to the current foreground color in the application. With Krita and Painter this happens only when a paint tool is selected; in GIMP it is always displayed, since the GIMP API does not allow querying the active tool.

Almost all apps have a GUI settings menu with a common layout which allows you to interactively edit your settings from within the application.

It is recommended that you look at the README for each specific plugin you plan to use, *especially* for GIMP and DaVinci Resolve, which have more limitations than the other plugins. For GIMP, it is difficult or impossible on some platforms to determine the active image; you will want to read through how to help the plugin find the image on MacOS and what fallback options are available on Linux. For Resolve, unlike all other apps, there is no supported pathway to have the plugin start at the same time as the application launches, at least in the non-Studio version of Resolve. Resolve is also the only application that does not have a GUI settings menu; creating UI elements is limited to the Studio version, which I do not have for development and testing. The Resolve README will explain how to start the plugin from within the app and how to edit the settings manually.

## Unsupported Apps
#### Made by others
Blender already has an excellent RPC plugin which inspired this project: https://github.com/abrasic/blendpresence.

Many of Adobe's Creative Cloud applications, such as Photoshop and After Effects, are supported by https://github.com/teeteeteeteetee/adobe-discord-rpc.

The Unreal Editor has a plugin (Windows-only) through itch.io: https://dn2.itch.io/editor-discord-rich-presence.
#### High Cost Barrier / Low Prospective Audience
Mari and Katana are not supported: non-commercial Mari users cannot use Python scripting, and Katana has no non-commercial version.

Cinema 4D is currently supported, but updates are unlikely to continue once my current subscription expires, unless Maxon provides developer licenses.

DaVinci Resolve has a scripting API, but non-Studio users can only execute commands from inside the application console; external file scripts will not execute.

For all of the above software, if someone with a commercial license was willing to help test the plugins, I would consider writing/maintaining them.
#### Currently Impossible
ZBrush, as much as I would like to create a plugin for it, does not have support in the API for the concept of long-running plugins; plugins are invoked from the scripting menu and expected to run on the main thread and return, blocking the application until they do so. It also exposes very little information to queries; e.g., the current brush cannot be determined. If the API expands, I will certainly look into creating a plugin.

Marvelous Designer has a richer query layer but also lacks threading support, making a plugin impossible.

Clip Studio Paint does not have a plugin system at all, at least within the United States. There is a C++ SDK for the Japanese version of the program; if this ever expands internationally, I'll consider writing a plugin.

Many other programs (Inkscape, Rebelle, Kdenlive, Material Maker, etc.) do not appear to have any scripting or plugin interfaces which which a RPC plugin could be created.

#### Bug Reports
If you're having a problem, open an issue and note the application, application version, and plugin version, as well as the tested application version mentioned in the plugin README. If your application version is older than the tested version, e.g., the plugin says it was tested on Nuke 17 and it is not working on Nuke 16, add the "Backwards Compatibility" tag when opening the issue. These issues will likely be lower priority than issues on supported versions, and in some cases may not be addressed at all: if the application version is so old it is using Python 2 instead of Python 3, I will not be rewriting the code to be Python 2 compliant. For most applications the Python executable should be bundled with the installation somewhere; if you can find it and check its version before creating the issue, please don't open an issue if you know it's Python 2.