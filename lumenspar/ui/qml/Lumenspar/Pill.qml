import QtQuick
import Lumenspar

// A small toggle pill: a label that is either on (tinted) or off.
Rectangle {
    id: pill
    property string label
    property bool checked: false
    property color tint: Theme.accent
    signal clicked()

    implicitHeight: 30
    implicitWidth: txt.implicitWidth + 24
    radius: 15
    color: checked ? Qt.rgba(tint.r, tint.g, tint.b, 0.18) : Theme.surfaceGlass
    border.width: 1
    border.color: checked ? tint : Theme.border

    Text {
        id: txt
        anchors.centerIn: parent
        text: pill.label
        color: pill.checked ? pill.tint : Theme.text
        font.pixelSize: 12
    }
    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: pill.clicked()
    }
}
