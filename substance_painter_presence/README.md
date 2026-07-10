## Installation Instructions
- Download the ZIP from Releases
- Open Painter and go to Python -> Plugins Folder
- Extract the ZIP into the 'startup' folder
- Restart Painter

## Accessing Settings
A new "Discord" dropdown will be added to the toolbar. Click it and select 'Settings' to access the GUI settings menu.

## Settings & Features
#### State and Details allow you to choose from:
- **Project name**: your project name, formatted as *"Project: __"*. Defaults to *"No project open"* if no project is open.
- **Project mesh count**: the number of mesh objects in your project, formatted as *"__ mesh[es]"*.
- **Project resource count**: the total number of resources used in your project, formatted as *"__ resource[s]"*.
- **Project layer count**: the number of layers in the current project, formatted as *"__ layer[s]"*.
- **Active material channel count**: The number of channels in the currently selected material (texture set), formatted as *"__ channel[s]"*.
- **Active texture set info**: the name and resolution of the active texture set, formatted as *"Texture set: __ (WxH)"*.
- **Project texture set info**: the number of texture sets and number of UV tiles (if used) on the active texture set, formatted as *"__ texture set[s]"* if UV tiles are not used, and *"__ texture set[s] (__ UV tile[s])"* if they are used.
- **Active layer info**: the name and blend mode of the active layer (if the blend mode is not "normal"). If 'layer' is not in the layer name, it will be prefixed with "Layer: ". For example: with normal blend mode, a layer named "Decals" would display as "Layer: Decals"; with multiply blend mode, a layer named "Layer 3" would display as "Layer 3 (Multiply)".

#### Icons
If you enable small icons, the icon for the tool you are currently using will be displayed as a small icon.
If you additionally enable colored icons, whenever you have the paint or physical paint tools selected, the small icon displayed on Discord will be a colored version of that tool's icon. 
Since the icon must be chosen from a set of <300 pre-uploaded icons, the color will not exactly match the color you are painting in. With two tools, 125 distinct colors chosen from across perceptual color space were selected for each; the color that appears should be close to what you are using.
Enabling colored icons will also create a tooltip on the icon with a name for the color among the 125 colors which was closest to your brush color, as well as the hex code of your actual color, e.g., "Painting in Imperial Purple (#602f6b)". The default is to use "creative" color names, but if you dislike those names, you can turn off the "evocative names" setting to use ISCC-NBS color names, which are a standardized set of straighforward names such as "Moderate Purple".

#### UI/Baking status
If you are in the Baking or IRay menus, the details field will override with the project name and the state field will override with "Adjusting baking settings" or "Previewing in IRay"; it is not possible to get active layer/stack information when not in the Painting UI so this override was chosen to present more useful information. Additionally, if you are actively baking, the state field will instead override with "Baking: x% progress".

## Troubleshooting Problems
If the plugin is not working, check the Substance Painter log for error messages before opening an issue. These will help to determine the cause of the error.