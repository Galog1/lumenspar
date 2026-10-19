import QtQuick
import QtQuick.Layouts
import Lumenspar

// Slides in over the top of any page when a newer release exists, and shows
// the download while it runs. "Later" hides it for this session only; the
// Check for updates controls on the main menu stay available.
Rectangle {
    id: banner
    readonly property bool shown: updates.showBanner || updates.state === "downloading"
                                  || updates.state === "installing"
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.top: parent.top
    anchors.topMargin: shown ? 14 : -height - 20
    Behavior on anchors.topMargin { NumberAnimation { duration: Theme.ease * 1.5; easing.type: Easing.OutCubic } }
    visible: anchors.topMargin > -height
    z: 100

    width: Math.min(parent.width - 40, 760)
    implicitHeight: col.implicitHeight + 28
    height: implicitHeight
    radius: Theme.radius
    color: Theme.surfaceHi
    border.width: 1
    border.color: Theme.accent

    ColumnLayout {
        id: col
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.margins: 18
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            spacing: 14
            Text {
                text: "⬆"
                color: Theme.accent
                font.pixelSize: 22
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Text {
                    Layout.fillWidth: true
                    text: "Lumenspar " + updates.latestVersion + " is available"
                    color: Theme.text
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                }
                Text {
                    Layout.fillWidth: true
                    text: updates.busy ? updates.status
                        : updates.canInstall ? "You have " + updates.currentVersion + ". Updating closes Lumenspar and starts the new version."
                        : "You have " + updates.currentVersion + ". This install cannot update itself; the release page has the download."
                    color: Theme.textDim
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
            }
            AccentButton {
                visible: updates.state === "idle"
                label: updates.canInstall ? "Update now" : "Open download page"
                onClicked: updates.install()
            }
            GhostButton {
                visible: updates.state === "idle"
                label: "Later"
                onClicked: updates.dismiss()
            }
            GhostButton {
                visible: updates.state === "downloading"
                label: "Cancel"
                onClicked: updates.cancel()
            }
        }

        Rectangle {   // download progress
            Layout.fillWidth: true
            visible: updates.state === "downloading" || updates.state === "installing"
            implicitHeight: 6
            radius: 3
            color: Theme.bgAlt
            Rectangle {
                width: parent.width * updates.fraction
                height: parent.height
                radius: 3
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: Theme.accent }
                    GradientStop { position: 1.0; color: Theme.accent2 }
                }
                Behavior on width { NumberAnimation { duration: Theme.ease } }
            }
        }
    }
}
