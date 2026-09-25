import QtQuick
import Lumenspar

Row {
    id: picker
    property int value: 4
    property int minimum: 1
    property int maximum: 5
    signal picked(int v)
    spacing: 6

    Repeater {
        model: picker.maximum
        delegate: Rectangle {
            required property int index
            readonly property int star: index + 1
            readonly property bool on: star <= picker.value
            readonly property bool allowed: star >= picker.minimum

            width: 38; height: 32; radius: 8
            color: on ? Qt.rgba(1, 1, 1, 0.06) : "transparent"
            border.width: 1
            border.color: on ? Theme.rarity(picker.value) : Theme.border
            opacity: allowed ? 1.0 : 0.35

            Text {
                anchors.centerIn: parent
                text: "★"
                font.pixelSize: 15
                color: on ? Theme.rarity(picker.value) : Theme.textDim
            }
            MouseArea {
                anchors.fill: parent
                enabled: allowed
                cursorShape: Qt.PointingHandCursor
                onClicked: { picker.value = star; picker.picked(star) }
            }
        }
    }
}
