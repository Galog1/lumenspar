import QtQuick
import QtQuick.Layouts
import Lumenspar

Rectangle {
    id: root
    property string title: ""
    property string subtitle: ""
    default property alias content: body.data

    radius: Theme.radius
    border.color: Theme.border
    border.width: 1
    gradient: Gradient {
        orientation: Gradient.Vertical
        GradientStop { position: 0.0; color: Theme.surfaceHi }
        GradientStop { position: 1.0; color: Theme.surface }
    }

    Layout.fillWidth: true
    // Height follows the content. The inner column is anchored on three edges
    // only: anchoring it to *fill* would make its height depend on this
    // Rectangle while this Rectangle's height depends on it, which QML
    // resolves as a binding loop and collapses the card onto itself.
    implicitHeight: col.implicitHeight + Theme.pad * 2
    Layout.preferredHeight: implicitHeight

    // Soft drop shadow: a stack of slightly larger, faint rectangles whose
    // overlap fades out with distance -- a faux blur that renders everywhere,
    // unlike shader-based effects. Offset downwards so it reads as light
    // from above rather than a dark outline.
    Repeater {
        model: 6
        delegate: Rectangle {
            required property int index
            anchors.fill: parent
            anchors.margins: -(index + 1) * 2
            anchors.topMargin: -(index + 1)
            anchors.bottomMargin: -(index + 1) * 3
            radius: Theme.radius + (index + 1) * 2
            color: Qt.rgba(0, 0, 0, 0.07)
            z: -1
        }
    }

    // 1px top inner highlight line
    Rectangle {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: Theme.pad
        anchors.rightMargin: Theme.pad
        anchors.topMargin: 1
        height: 1
        color: Qt.rgba(1, 1, 1, 0.06)
    }

    // thin accent bar on the left edge, only on hover
    HoverHandler {
        id: hover
        enabled: true
    }
    Rectangle {
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.topMargin: 10
        anchors.bottomMargin: 10
        width: 3
        radius: 1.5
        color: Theme.accent
        opacity: hover.hovered ? 1.0 : 0.0
        Behavior on opacity { NumberAnimation { duration: Theme.ease } }
    }

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
            RowLayout {
                Layout.fillWidth: true
                spacing: 9
                Rectangle {
                    width: 9; height: 9; radius: 4.5
                    color: Theme.accent
                    Layout.alignment: Qt.AlignVCenter
                    Rectangle {   // faint glow ring around the dot
                        anchors.fill: parent
                        anchors.margins: -4
                        radius: width / 2
                        color: "transparent"
                        border.color: Qt.rgba(0.31, 0.847, 0.91, 0.35)
                        border.width: 1
                    }
                }
                Text {
                    text: root.title
                    color: Theme.text
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    Layout.alignment: Qt.AlignVCenter
                }
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
