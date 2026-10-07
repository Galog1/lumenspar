import QtQuick
import Lumenspar

Rectangle {
    id: btn
    property string label: ""
    property bool enabledState: true
    signal clicked()

    implicitHeight: 38
    implicitWidth: Math.max(110, txt.implicitWidth + 34)
    radius: 9
    color: ma.containsMouse ? Qt.rgba(0.11, 0.15, 0.22, 0.9) : Theme.surfaceGlass
    border.width: 1
    border.color: ma.containsMouse ? Theme.accent : Theme.border
    opacity: enabledState ? 1.0 : 0.45
    Behavior on color { ColorAnimation { duration: Theme.ease } }
    Behavior on border.color { ColorAnimation { duration: Theme.ease } }

    Text {
        id: txt
        anchors.centerIn: parent
        text: btn.label
        color: Theme.text
        font.pixelSize: 13
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
