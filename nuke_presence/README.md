## Installation Instructions
- Download the ZIP from releases
- Extract the folder into your ~/.nuke directory (on Windows: C:/Users/Your_User_Name/.nuke)
- Open 'init.py' in ~/.nuke and copy the following text onto a new line after existing lines: `nuke.pluginAddPath("./NukePresence")`

## Accessing Settings
A new 'Discord' tab will be added on the top menu. By opening it you can start or stop Rich Presence updates, and open the GUI menu. 

## Non-Commercial Warning
The Python API in Nuke Indie and Nuke Non-Commercial does not allow more than 10 node queries over an entire session. This means that all information types that require node queries (active node, read/write node count, viewer info) would fail and cause an error message in the console after more than 10 RPC updates. For this reason, those information types are disabled in Non-Commercial and Indie sessions.

## Settings & Features
#### State and Details allow you to choose from:
- **Comp name**: your script name, e.g., *'comp.nk'*. Defaults to *'Unsaved script'* on new comps.
- **Memory usage**: the amount of system memory used by the current comp, e.g., *'Using 1.8GB of memory'*
- **Node count**: the number of nodes in your comp graph, formatted as *'_ node[s]'*. Note that this *may be inaccurate* if you are a non-commercial Nuke user: the non-commercial API does not return a count of nodes within groups, only the number of nodes or groups at the root level of the comp graph.
- **Active Node**: the node (name and class) you currently have selected, if any, formatted as *'`name` (`class`)'*, or *'No nodes selected'* if none are selected. Since small nodes are also displayed in the small icon (if it is enabled), this will be skipped in any cycle where the node is displayed as the icon; however, if you manually select it as the state or details type, it will still display.
- **Read/write node count**: the number of read nodes and write nodes in your comp. If both types are in the graph, the result will be formatted as *'_ read node[s]; _ write node[s]'*. If only one type is present, the format is *'_ [read/write] node[s]'*.
- **Layer count**: the number of layers in the current comp, formatted as *'_ layer[s]'*
- **Viewer info**: the name of the node being viewed through the viewer, as well as the channel and viewer process being viewed, e.g., *'Viewing Read1 in sRGB'*
- **Color management**: the color management model of the comp, formatted as *'Color management: _'*
- **Format**: the format and resolution of the comp, e.g., *'2K Super 35(full-ap) (2048x1556)'*
- **Proxy info**: the proxy and downrez values for the active viewer (if non-default), e.g., *'Proxy 0.5x, downrez 1/4'*

#### Rendering
If you enable rendering details, when you are rendering a comp it will override the details field with information about the render: comp name, resolution, and frames rendered. For example: *'Rendering comp_name.nk: 3840x2160, Frame 901'*.

#### Icons
If you enable small icons and you are a commercial user, the plugin will try to display an icon for the node you currently have selected. Not all nodes will be displayed, as only a subset of the nodes were available as SVGs which could be rendered to the size required by Discord. A tooltip will also be added showing the class of the node (e.g., 'Viewer') and the name of the node (e.g., 'Viewer1').