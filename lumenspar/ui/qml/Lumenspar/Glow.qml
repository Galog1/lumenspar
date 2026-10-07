import QtQuick
import Lumenspar

// A soft radial glow built from concentric translucent circles.
// Renders cleanly on any backend (no shaders), which keeps the offscreen
// screenshots identical to the real app.
Item {
    id: glow
    property color color: Theme.accent
    property real alpha: 0.25
    property int rings: 10

    Repeater {
        model: glow.rings
        delegate: Rectangle {
            required property int index
            anchors.centerIn: parent
            width: parent.width * (index + 1) / glow.rings
            height: parent.height * (index + 1) / glow.rings
            radius: width / 2
            color: Qt.rgba(glow.color.r, glow.color.g, glow.color.b,
                           glow.alpha / glow.rings)
        }
    }
}
