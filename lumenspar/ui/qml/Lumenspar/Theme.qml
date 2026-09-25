pragma Singleton
import QtQuick

QtObject {
    // Lumenspar: a luminous cyan crystal, against the dark of The Chasm.
    readonly property color bg:        "#0B0E14"
    readonly property color bgAlt:     "#0F1420"
    readonly property color surface:   "#151B27"
    readonly property color surfaceHi: "#1B2231"
    readonly property color border:    "#242D3D"
    readonly property color text:      "#E8EDF7"
    readonly property color textDim:   "#8A94A9"
    readonly property color accent:    "#4FD8E8"
    readonly property color accent2:   "#6E7BFF"
    readonly property color danger:    "#E8686B"
    readonly property color ok:        "#5AD6A0"

    readonly property int radius: 14
    readonly property int pad: 18
    readonly property int gap: 14

    function rarity(n) {
        switch (n) {
        case 5: return "#E8B45A";
        case 4: return "#A868D8";
        case 3: return "#5AA6D8";
        case 2: return "#5FBF8B";
        default: return "#8A94A9";
        }
    }
}
