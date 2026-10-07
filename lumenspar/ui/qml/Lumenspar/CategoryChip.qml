import QtQuick
import Lumenspar

Item {
    id: chip
    property string label: ""
    property string glyph: ""
    property bool checked: false
    property bool available: true
    property string note: ""
    property color color: Theme.accent   // per-category tint
    signal toggled(bool on)

    implicitWidth: 118
    implicitHeight: 74
    opacity: available ? 1.0 : 0.45
    scale: hover.hovered ? 1.02 : 1.0
    Behavior on scale { NumberAnimation { duration: Theme.ease } }

    Rectangle {
        anchors.fill: parent
        radius: 12
        color: chip.checked ? Qt.rgba(chip.color.r, chip.color.g, chip.color.b, 0.18)
                            : Theme.surfaceGlass
        border.width: chip.checked ? 1.5 : 1
        border.color: chip.checked ? Qt.rgba(chip.color.r, chip.color.g, chip.color.b, 0.6)
                                   : Theme.border
        Behavior on color { ColorAnimation { duration: Theme.ease } }
        Behavior on border.color { ColorAnimation { duration: Theme.ease } }
    }

    Column {
        anchors.centerIn: parent
        spacing: 6
        Rectangle {   // glyph circle
            width: 30; height: 30; radius: 15
            anchors.horizontalCenter: parent.horizontalCenter
            color: chip.checked ? chip.color : Qt.rgba(1, 1, 1, 0.04)
            border.width: 1
            border.color: chip.checked ? Qt.rgba(chip.color.r, chip.color.g, chip.color.b, 0.5)
                                       : "transparent"
            Behavior on color { ColorAnimation { duration: Theme.ease } }
            Behavior on border.color { ColorAnimation { duration: Theme.ease } }
            Text {
                anchors.centerIn: parent
                text: chip.glyph
                font.pixelSize: 15
                color: chip.checked ? "#08121A" : Theme.textDim
                Behavior on color { ColorAnimation { duration: Theme.ease } }
            }
        }
        Text {
            text: chip.label
            font.pixelSize: 12
            font.weight: chip.checked ? Font.DemiBold : Font.Normal
            color: chip.checked ? chip.color : Theme.textDim
            anchors.horizontalCenter: parent.horizontalCenter
            Behavior on color { ColorAnimation { duration: Theme.ease } }
        }
        Text {
            text: chip.note
            visible: chip.note !== ""
            font.pixelSize: 10
            color: Theme.textDim
            anchors.horizontalCenter: parent.horizontalCenter
        }
    }

    HoverHandler {
        id: hover
        enabled: chip.available
    }
    MouseArea {
        anchors.fill: parent
        enabled: chip.available
        cursorShape: chip.available ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: chip.toggled(!chip.checked)
    }
}
