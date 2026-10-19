import QtQuick
import Lumenspar

// A small segmented switch: one pill with a segment per option. Emits picked(value);
// the owner sets `current` (so the switch always shows what the backend holds).
Rectangle {
    id: seg
    property var options: []            // [{ value: "cv", label: "CV" }, ...]
    property string current: ""
    signal picked(string value)

    implicitWidth: row.implicitWidth + 8
    implicitHeight: 34
    radius: height / 2
    color: Theme.surfaceGlass
    border.width: 1
    border.color: Theme.border

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 2
        Repeater {
            model: seg.options
            delegate: Rectangle {
                id: opt
                required property var modelData
                readonly property bool on: modelData.value === seg.current
                width: optLabel.implicitWidth + 30
                height: 26
                radius: 13
                color: on ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.20)
                          : (area.containsMouse ? Qt.rgba(1, 1, 1, 0.05) : "transparent")
                border.width: on ? 1 : 0
                border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.55)
                Behavior on color { ColorAnimation { duration: Theme.ease } }
                Text {
                    id: optLabel
                    anchors.centerIn: parent
                    text: opt.modelData.label
                    color: opt.on ? Theme.accent : Theme.textDim
                    font.pixelSize: 12
                    font.weight: opt.on ? Font.DemiBold : Font.Normal
                    font.letterSpacing: 0.6
                }
                MouseArea {
                    id: area
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: seg.picked(opt.modelData.value)
                }
            }
        }
    }
}
