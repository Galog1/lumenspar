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
    color: ma.containsMouse ? Theme.surfaceHi : "transparent"
    border.color: Theme.border
    border.width: 1
    opacity: enabledState ? 1.0 : 0.45
    Behavior on color { ColorAnimation { duration: 110 } }

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
}
