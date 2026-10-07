import QtQuick
import Lumenspar

Rectangle {
    id: pill
    property string label: ""
    property bool good: true
    implicitHeight: 26
    implicitWidth: row.implicitWidth + 20
    radius: 13
    color: Theme.surfaceGlass
    border.width: 1
    border.color: Theme.border

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 8
        Item {
            width: 22; height: 22
            anchors.verticalCenter: parent.verticalCenter
            Rectangle {   // glow ring: 3x the dot's radius at 20% opacity
                anchors.centerIn: parent
                width: 21; height: 21; radius: 10.5
                color: "transparent"
                border.color: Qt.rgba(pill.good ? Theme.ok.r : Theme.danger.r,
                                      pill.good ? Theme.ok.g : Theme.danger.g,
                                      pill.good ? Theme.ok.b : Theme.danger.b, 0.2)
                border.width: 1
            }
            Rectangle {   // dot
                anchors.centerIn: parent
                width: 7; height: 7; radius: 4
                color: pill.good ? Theme.ok : Theme.danger
                SequentialAnimation on scale {
                    running: pill.good
                    loops: Animation.Infinite
                    NumberAnimation { to: 0.8; duration: 800 }
                    NumberAnimation { to: 1.15; duration: 800 }
                }
            }
        }
        Text {
            text: pill.label
            color: Theme.textDim
            font.pixelSize: 12
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
