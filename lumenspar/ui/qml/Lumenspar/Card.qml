import QtQuick
import QtQuick.Layouts
import Lumenspar

Rectangle {
    id: root
    property string title: ""
    property string subtitle: ""
    default property alias content: body.data

    color: Theme.surface
    radius: Theme.radius
    border.color: Theme.border
    border.width: 1

    Layout.fillWidth: true
    // Height follows the content. The inner column is anchored on three edges
    // only: anchoring it to *fill* would make its height depend on this
    // Rectangle while this Rectangle's height depends on it, which QML
    // resolves as a binding loop and collapses the card onto itself.
    implicitHeight: col.implicitHeight + Theme.pad * 2
    Layout.preferredHeight: implicitHeight

    ColumnLayout {
        id: col
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: Theme.pad
        spacing: 12

        ColumnLayout {
            spacing: 3
            Layout.fillWidth: true
            visible: root.title !== ""
            Text {
                text: root.title
                color: Theme.text
                font.pixelSize: 15
                font.weight: Font.DemiBold
            }
            Text {
                text: root.subtitle
                color: Theme.textDim
                font.pixelSize: 12
                visible: root.subtitle !== ""
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }

        ColumnLayout {
            id: body
            Layout.fillWidth: true
            spacing: 10
        }
    }
}
