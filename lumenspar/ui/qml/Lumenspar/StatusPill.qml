import QtQuick
import Lumenspar

Rectangle {
    id: pill
    property string label: ""
    property bool good: true
    implicitHeight: 26
    implicitWidth: row.implicitWidth + 20
    radius: 13
    color: Theme.surfaceHi
    border.width: 1
    border.color: Theme.border

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 7
        Rectangle {
            width: 7; height: 7; radius: 4
            color: pill.good ? Theme.ok : Theme.danger
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: pill.label
            color: Theme.textDim
            font.pixelSize: 12
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
