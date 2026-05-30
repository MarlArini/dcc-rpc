## Installation Instructions
- Download the ZIP from releases
- Open Designer and go to Tools -> Plugin Manager -> Install
- Select the downloaded ZIP

## Accessing Settings
A new 'Discord' dropdown will be added to the toolbar. Click it and select 'Settings' to access the GUI settings menu. You can also pause and restart RPC updates from the dropdown.

## Settings & Features
#### State and Details allow you to choose from:
- **Project name**: the current package name, including extension: e.g., *'Fabrics.sbs'*. If no packages are open, *'No package open'* is displayed.
- **Active node**: the type of the currently selected node, e.g., *'Uniform color'*.
- **Node count**: the number of nodes in the current graph, formatted as *'__ node[s]'*.
- **Output node count**: the number of output nodes in the current graph, formatted as *'__ output node[s]'*.
- **Export resolution**: the resolution of the first output node in a query for all output nodes. This assumes and works best if all output nodes have the same resolution. The format is *'[Width]x[Height]'*.
- **Material model**: the material model in use for the graph (if it is not 'Undefined'), e.g., *'OpenPBR v1.1'*.
- **Resource count**: the total number of resources in the current package, formatted as *'__ resource[s]'*.
- **Color space**: the color space of the current graph, e.g., *'Color space: sRGB'*.
TODO update all above

#### Icons
If you enable small icons, the icon for the node you currently have selected will be displayed, ***IF*** it is an atomic node. 
(*I could not find a way to get image files for the icons of the non-atomic nodes; even the atomic node icons are from the Designer documentation online and not from the application. If someone knows a way to extract the icons from the application through PySide6 I would be interested; all of the elements that hold icons appear to be in custom opaque QtWidget objects with no children.*)