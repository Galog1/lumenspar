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

    // extra tokens for the luminous-crystal look
    readonly property color accentGlow:   Qt.rgba(0.31, 0.847, 0.91, 0.35)   // accent at ~35% alpha
    readonly property color surfaceGlass: Qt.rgba(0.082, 0.106, 0.153, 0.80) // surface at ~80% alpha
    readonly property color gradientA:    accent
    readonly property color gradientB:    accent2
    readonly property color glow:         "#8E9AFF"   // soft luminous indigo (accent2's glow)
    readonly property int ease:           160         // ms

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

    function element(e) {
        switch (e) {
        case "pyro": return "#EF7938";
        case "hydro": return "#4CC2F1";
        case "anemo": return "#74C2A8";
        case "electro": return "#B08FC2";
        case "dendro": return "#A5C83B";
        case "cryo": return "#9FD6E3";
        case "geo": return "#FAB632";
        default: return accent;
        }
    }
}
