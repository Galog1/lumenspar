import QtQuick
import Lumenspar

// Layered window backdrop: base colour, two soft radial glows and a very
// faint diagonal facet pattern. Purely decorative; sits behind the body
// content (z = -1) and never intercepts input.
Item {
    id: backdrop

    Rectangle {
        anchors.fill: parent
        color: Theme.bg
    }

    // cyan glow, top left
    Glow {
        x: -160; y: -190
        width: 580; height: 580
        color: Theme.accent
        alpha: 0.22
    }

    // indigo glow, bottom right
    Glow {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: -170
        anchors.bottomMargin: -210
        width: 660; height: 660
        color: Theme.glow
        alpha: 0.22
    }

    // faint diagonal facet lines (2-3% white)
    Rectangle {
        x: parent.width * 0.05; y: -parent.height * 0.2
        width: 2; height: parent.height * 1.4
        rotation: -14; color: Qt.rgba(1, 1, 1, 0.03)
    }
    Rectangle {
        x: parent.width * 0.24; y: -parent.height * 0.25
        width: 2; height: parent.height * 1.5
        rotation: -18; color: Qt.rgba(1, 1, 1, 0.025)
    }
    Rectangle {
        x: parent.width * 0.43; y: -parent.height * 0.2
        width: 2; height: parent.height * 1.4
        rotation: -15; color: Qt.rgba(1, 1, 1, 0.03)
    }
    Rectangle {
        x: parent.width * 0.62; y: -parent.height * 0.25
        width: 2; height: parent.height * 1.5
        rotation: -20; color: Qt.rgba(1, 1, 1, 0.025)
    }
    Rectangle {
        x: parent.width * 0.81; y: -parent.height * 0.2
        width: 2; height: parent.height * 1.4
        rotation: -16; color: Qt.rgba(1, 1, 1, 0.03)
    }
    Rectangle {
        x: parent.width * 0.99; y: -parent.height * 0.25
        width: 2; height: parent.height * 1.5
        rotation: -24; color: Qt.rgba(1, 1, 1, 0.025)
    }
}
