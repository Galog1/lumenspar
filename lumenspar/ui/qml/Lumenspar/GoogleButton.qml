import QtQuick
import Lumenspar

// Google's "Sign in with Google" button, dark theme, pill shape, as its
// branding guidelines require for a button that starts a Google sign-in:
// the standard "G", #131314 fill, #8E918F outline, #E3E3E3 Roboto Medium.
Rectangle {
    id: btn
    property string label: "Sign in with Google"
    property bool enabledState: true
    signal clicked()

    implicitHeight: 40
    implicitWidth: row.implicitWidth + 24
    radius: 20
    color: "#131314"
    border.width: 1
    border.color: enabledState ? "#8E918F" : Qt.rgba(0.557, 0.569, 0.561, 0.12)
    opacity: enabledState ? 1.0 : 0.6

    Rectangle {   // hover / press state layer
        anchors.fill: parent
        radius: parent.radius
        color: "#E3E3E3"
        opacity: !btn.enabledState ? 0 : ma.pressed ? 0.12 : ma.containsMouse ? 0.08 : 0
    }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 10
        Image {
            anchors.verticalCenter: parent.verticalCenter
            source: "google-g.svg"
            sourceSize.width: 20
            sourceSize.height: 20
            width: 20; height: 20
            opacity: btn.enabledState ? 1.0 : 0.38
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: btn.label
            color: "#E3E3E3"
            opacity: btn.enabledState ? 1.0 : 0.38
            font.family: "Roboto"
            font.weight: Font.Medium
            font.pixelSize: 14
        }
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        enabled: btn.enabledState
        cursorShape: Qt.PointingHandCursor
        onClicked: btn.clicked()
    }
}
