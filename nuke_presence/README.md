## Installation Instructions
- Download the ZIP from releases
- Extract the folder into your ~/.nuke directory (on Windows: C:/Users/Your_User_Name/.nuke)
- Open 'init.py' in ~/.nuke and add copy the following text onto a new line after existing lines: `nuke.pluginAddPath("./NukePresence")`

## Accessing Settings
A new 'Discord' tab will be added on the top menu. By opening it you can start or stop Rich Presence updates, and open the GUI menu. 

## Settings & Features
#### State and Details allow you to choose from:
- **Comp name**: your script name, e.g., *'comp.nk'*. Defaults to *'Unsaved script'* on new comps.
- **Memory usage**: the amount of system memory used by the current comp, e.g., *'Using 1.8GB of memory'*
- **Node count**: the number of nodes in your comp graph, formatted as *'_ node[s]'*. Note that this *may be inaccurate* if you are a non-commercial Nuke user: the non-commercial API does not return a count of nodes within groups, only the number of nodes or groups at the root level of the comp graph.
- **Active Node**: the node (name and class) you currently have selected, if any, formatted as *'`name` (`class`)'*, or *'No nodes selected'* if none are selected. Since small nodes are also displayed in the small icon (if it is enabled), this will be skipped in any cycle where the node is displayed as the icon; however, if you manually select it as the state or details type, it will still display. This will sometimes print an error to the console and not return a value on Non-Commercial Nuke, and I'm not really sure why (the message says the limit of 10 nodes has been reached, but appeared at times with only 3 nodes in the graph, and disappeared when more were added). A global setting exists to disable these queries if you are experiencing the messages and dislike them.
- **Read/write node count**: the number of read nodes and write nodes in your comp. If both types are in the graph, the result will be formatted as *'_ read node[s]; _ write node[s]'*. If only one type is present, the format is *'_ [read/write] node[s]'*. **If you are a non-commercial user this will never return more than 10 nodes and may result in console errors**. The reason for this is that non-commercial users can query a maximum of 10 nodes at a time; if there are more than 10 nodes in a result the result will be truncated and an uncatchable error message will be printed to the console. If you are a non-commercial user and dislike this, there is an option to disable node queries, which will skip the queries and prevent the error messages.
- **Layer count**: the number of layers in the current comp, formatted as *'_ layer[s]'*
- **Viewer info**: the name of the node being viewed through the viewer, as well as the channel being viewed, e.g., *'Viewing Read1 through RGBA'*
TODO more accurate above
- **Color management**: the color management model of the comp, formatted as *'Color management: _'*
- **Format**: the format and resolution of the comp, e.g., *'2K Super 35(full-ap) (2048x1556)'*
- **Proxy info**: the proxy and downrez values for the active viewer (if non-default), e.g., *'Proxy 0.5x, downrez 1/4'*

#### Rendering
If you enable rendering details, when you are rendering a comp it will override the details field with information about the render: the comp name, the current frame, and the frame range. For example: *'Rendering comp_name.nk: Frame 37 of 100'*. This is only an approximation and may be inaccurate, since it uses the global timeline frame range; the beforeRenderStart callback does not appear to provide the specific frame range being rendered as arguments so it can only be inferred/guessed at.

#### Icons
If you enable small icons, the plugin will try to disply an icon for the node you currently have selected. There are more Nuke nodes than the limit for icons on a Rich Presence application, so some nodes will not appear; however, there are more than 200 supported nodes including many of the common nodes. A tooltip will also be added showing the class of the node (e.g., 'Viewer') and the name of the node (e.g., 'Viewer1').

Some of the icons were rendered to high resolution output from SVG images. Others could only be found as lower-resolution (~40x40px) images and were upscaled with linear interpolation (linear was chosen to keep the colors and shapes as accurate as possible rather than introducing banding or artifacts). They will be downscaled again to a similar size by Discord to display as the small icon, presumably with non-linear interpolation, but may still appear slightly pixelated. If you dislike this, there is a setting to disable the use of upscaled small icons, using only the high-resolution SVG-rendered icons.