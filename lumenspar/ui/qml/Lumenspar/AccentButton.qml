import QtQuick
import Lumenspar

Rectangle {
    id: btn
    property string label: ""
    property bool enabledState: true
    signal clicked()

    implicitHeight: 42
    implicitWidth: Math.max(140, txt.implicitWidth + 44)
    radius: 10
    opacity: enabledState ? 1.0 : 0.45
    gradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop { position: 0.0; color: ma.pressed ? Qt.darker(Theme.accent, 1.2) : Theme.accent }
        GradientStop { position: 1.0; color: ma.pressed ? Qt.darker(Theme.accent2, 1.2) : Theme.accent2 }
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
        enabled: btn.enabledState
        cursorShape: Qt.PointingHandCursor
        onClicked: btn.clicked()
    }
    scale: ma.pressed ? 0.985 : 1.0
    Behavior on scale { NumberAnimation { duration: 80 } }
}
