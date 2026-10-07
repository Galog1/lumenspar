import QtQuick
import Lumenspar

Rectangle {
    id: btn
    property string label: ""
    property bool enabledState: true
    property bool pulsing: false   // breathing glow (used while scanning)
    signal clicked()

    implicitHeight: 42
    implicitWidth: Math.max(140, txt.implicitWidth + 44)
    radius: 10
    opacity: enabledState ? 1.0 : 0.45
    gradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop { position: 0.0; color: ma.pressed ? Qt.darker(Theme.gradientA, 1.2) : Theme.gradientA }
        GradientStop { position: 1.0; color: ma.pressed ? Qt.darker(Theme.gradientB, 1.2) : Theme.gradientB }
    }

    // Accent glow beneath the button: stacked faint rings fade out with
    // distance (a faux blur -- plain rects render everywhere).
    Item {
        id: glowFx
        anchors.fill: parent
        z: -1
        opacity: 0.9
        Repeater {
            model: 5
            delegate: Rectangle {
                required property int index
                anchors.fill: parent
                anchors.margins: -(index + 1) * 2
                radius: 10 + (index + 1) * 2
                color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.09)
            }
        }
        SequentialAnimation on opacity {
            running: btn.pulsing
            loops: Animation.Infinite
            NumberAnimation { to: 0.3; duration: 1100 }
            NumberAnimation { to: 1.0; duration: 1500 }
        }
    }

    // hover brighten overlay
    Rectangle {
        anchors.fill: parent
        radius: 10
        color: Qt.rgba(1, 1, 1, 0.08)
        opacity: ma.containsMouse ? 1.0 : 0.0
        Behavior on opacity { NumberAnimation { duration: Theme.ease } }
    }

    Text {
        id: txt
        anchors.centerIn: parent
        text: btn.label
        color: "#08121A"
        font.pixelSize: 14
        font.weight: Font.Bold
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        enabled: btn.enabledState
        cursorShape: Qt.PointingHandCursor
        onClicked: btn.clicked()
    }
    scale: ma.pressed ? 0.97 : 1.0
    Behavior on scale { NumberAnimation { duration: Theme.ease } }
}
