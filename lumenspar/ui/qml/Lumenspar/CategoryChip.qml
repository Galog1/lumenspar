import QtQuick
import Lumenspar

Rectangle {
    id: chip
    property string label: ""
    property string glyph: ""
    property bool checked: false
    property bool available: true
    property string note: ""
    signal toggled(bool on)

    implicitWidth: 118
    implicitHeight: 74
    opacity: available ? 1.0 : 0.45
    radius: 12
    color: checked ? Qt.rgba(0.31, 0.85, 0.91, 0.10) : Theme.surfaceHi
    border.width: checked ? 1.5 : 1
    border.color: checked ? Theme.accent : Theme.border
    Behavior on color { ColorAnimation { duration: 120 } }

    Column {
        anchors.centerIn: parent
        spacing: 6
        Text {
            text: chip.glyph
            font.pixelSize: 20
            color: chip.checked ? Theme.accent : Theme.textDim
            anchors.horizontalCenter: parent.horizontalCenter
            Behavior on color { ColorAnimation { duration: 120 } }
        }
        Text {
            text: chip.label
            font.pixelSize: 12
            font.weight: chip.checked ? Font.DemiBold : Font.Normal
            color: chip.checked ? Theme.text : Theme.textDim
            anchors.horizontalCenter: parent.horizontalCenter
        }
        Text {
            text: chip.note
            visible: chip.note !== ""
            font.pixelSize: 10
            color: Theme.textDim
            anchors.horizontalCenter: parent.horizontalCenter
        }
    }

    MouseArea {
        anchors.fill: parent
        enabled: chip.available
        cursorShape: chip.available ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: chip.toggled(!chip.checked)
    }
}
