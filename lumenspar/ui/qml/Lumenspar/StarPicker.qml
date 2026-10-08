import QtQuick
import Lumenspar

Row {
    id: picker
    property int value: 4
    property int minimum: 1
    property int maximum: 5
    property int hoverIndex: 0
    signal picked(int v)
    spacing: 6

    // Lit stars take the game's colour for the chosen rarity (gold 5, purple 4,
    // blue 3, green 2, grey 1) -- or for the hovered one, as a preview.
    readonly property color tint: Theme.rarity(hoverIndex > 0 ? hoverIndex : value)

    Repeater {
        model: picker.maximum
        delegate: Item {
            required property int index
            readonly property int star: index + 1
            readonly property bool on: star <= picker.value
            readonly property bool allowed: star >= picker.minimum
            readonly property bool lit: on || (hoverIndex > 0 && star <= picker.hoverIndex)

            width: 38; height: 32
            opacity: allowed ? 1.0 : 0.35

            Rectangle {   // cell background
                anchors.fill: parent
                radius: 8
                color: lit ? Qt.rgba(picker.tint.r, picker.tint.g, picker.tint.b, 0.10)
                           : "transparent"
                border.width: 1
                border.color: lit ? Qt.rgba(picker.tint.r, picker.tint.g, picker.tint.b, 0.55)
                                  : Theme.border
                Behavior on color { ColorAnimation { duration: Theme.ease } }
                Behavior on border.color { ColorAnimation { duration: Theme.ease } }
            }

            Text {   // faint glow behind the star
                anchors.centerIn: parent
                text: "★"
                font.pixelSize: 26
                color: Qt.rgba(picker.tint.r, picker.tint.g, picker.tint.b, lit ? 0.20 : 0.0)
                Behavior on color { ColorAnimation { duration: Theme.ease } }
            }
            Text {   // main star
                anchors.centerIn: parent
                text: "★"
                font.pixelSize: 15
                color: lit ? picker.tint : Theme.textDim
                Behavior on color { ColorAnimation { duration: Theme.ease } }
            }

            HoverHandler {
                onHoveredChanged: {
                    if (hovered)
                        picker.hoverIndex = star
                    else if (picker.hoverIndex === star)
                        picker.hoverIndex = 0
                }
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
