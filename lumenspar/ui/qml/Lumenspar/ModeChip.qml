import QtQuick
import QtQuick.Layouts
import Lumenspar

// A segment of the Reader-mode toggle: two of these sit side by side in a
// RowLayout and switch backend.readerMode. Same visual language as
// CategoryChip (tinted glass fill, glyph disc, tinted text, hover lift) but
// with a clicked() signal -- a modifier toggle must not uncheck itself by
// clicking, so it does not reuse CategoryChip's toggled(on) flip.
Item {
    id: chip
    property string label: ""
    property string glyph: ""
    property bool checked: false
    property color color: Theme.accent   // per-mode tint
    signal clicked()

    Layout.fillWidth: true
    implicitWidth: 160
    implicitHeight: 64

    scale: ma.containsMouse ? 1.02 : 1.0
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

    Rectangle {   // glyph disc
        anchors.left: parent.left
        anchors.leftMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        width: 30; height: 30; radius: 15
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
        anchors.left: parent.left
        anchors.leftMargin: 54
        anchors.right: parent.right
        anchors.rightMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        text: chip.label
        elide: Text.ElideRight
        font.pixelSize: 12
        font.weight: chip.checked ? Font.DemiBold : Font.Normal
        color: chip.checked ? chip.color : Theme.textDim
        Behavior on color { ColorAnimation { duration: Theme.ease } }
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: chip.clicked()
    }
}
