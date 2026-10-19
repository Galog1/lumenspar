import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import Lumenspar

ApplicationWindow {
    id: win
    // Which page is showing: "menu", "scanner", "wishes", "cards" or "optimizer". Every page is
    // created once and only hidden, so a running scan or import, and its
    // log, carry on while another page is open.
    property string page: "menu"
    width: 1180
    height: 800
    minimumWidth: 940
    minimumHeight: 640
    visible: true
    title: "Lumenspar"
    color: Theme.bg
    font.family: "Inter"

    // cyan→indigo interpolation for the gradient title
    function mixColor(t) {
        return Qt.rgba(Theme.accent.r + (Theme.accent2.r - Theme.accent.r) * t,
                       Theme.accent.g + (Theme.accent2.g - Theme.accent.g) * t,
                       Theme.accent.b + (Theme.accent2.b - Theme.accent.b) * t, 1)
    }

    // ── header ────────────────────────────────────────────────────────
    header: Rectangle {
        height: 74
        color: Theme.bgAlt
        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width; height: 1
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.5; color: Qt.rgba(0.31, 0.847, 0.91, 0.5) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 24
            anchors.rightMargin: 24
            spacing: 16

            GhostButton {
                label: "‹  Menu"
                visible: win.page !== "menu"
                implicitWidth: 92
                onClicked: win.page = "menu"
            }

            Item {
                width: 38; height: 38
                Glow {   // soft animated breath behind the icon
                    anchors.centerIn: parent
                    width: 64; height: 64
                    color: Theme.accent
                    alpha: 0.45
                    opacity: 0.7
                    SequentialAnimation on opacity {
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.55; duration: 1300 }
                        NumberAnimation { to: 1.0; duration: 1300 }
                    }
                }
                Image {
                    id: headerIcon
                    anchors.centerIn: parent
                    width: 34; height: 34
                    source: Qt.resolvedUrl("../../../install/lumenspar.svg")
                    sourceSize: Qt.size(68, 68)
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                    visible: status === Image.Ready
                }
                Rectangle {   // fallback: gradient tile with the crystal glyph
                    id: iconFallback
                    anchors.centerIn: parent
                    width: 34; height: 34; radius: 9
                    visible: headerIcon.status === Image.Error
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: Theme.accent }
                        GradientStop { position: 1.0; color: Theme.accent2 }
                    }
                    Text { anchors.centerIn: parent; text: "◆"; font.pixelSize: 16; color: "#08121A" }
                }
            }

            ColumnLayout {
                spacing: 0
                Row {   // "LUMENSPAR", each letter tinted cyan→indigo
                    Repeater {
                        model: "LUMENSPAR".length
                        delegate: Text {
                            required property int index
                            text: "LUMENSPAR".charAt(index)
                            color: win.mixColor(index / 8)
                            font.pixelSize: 17
                            font.weight: Font.Bold
                            font.letterSpacing: 2.4
                        }
                    }
                }
                Text {
                    text: win.page === "scanner" ? "Inventory scanner · exports .GOOD"
                        : win.page === "wishes" ? "Wish counter · pity and 50/50 from your wish history"
                        : win.page === "cards" ? "Build cards · your characters via Enka.Network and HoYoLAB"
                        : win.page === "optimizer" ? "Optimizer · best artifacts for a character from your scan"
                        : "Genshin Impact companion"
                    color: Theme.textDim
                    font.pixelSize: 12
                }
            }

            Item { Layout.fillWidth: true }

            Row {
                spacing: 10
                visible: win.page === "scanner"
            StatusPill { label: (backend.aiOnly || backend.readerMode === "ai") ? "Gemini" : "OCR"; good: backend.readerReady }
            StatusPill { label: backend.matcherBackend.indexOf("rapidfuzz") === 0 ? "rapidfuzz" : "difflib"; good: backend.matcherBackend.indexOf("rapidfuzz") === 0 }
            StatusPill { label: backend.vocabSummary; good: true }
            }
        }
    }

    // ── body ──────────────────────────────────────────────────────────
    // layered backdrop behind the settings/activity columns
    Backdrop {
        anchors.fill: parent
    }

    component Page: Item {
        anchors.fill: parent
        property string name
        visible: opacity > 0
        opacity: win.page === name ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.ease } }
    }

    Page {
        name: "menu"
        MenuPage { anchors.fill: parent; onOpen: function(target) { win.page = target } }
    }
    Page {
        name: "scanner"
        ScannerPage { anchors.fill: parent }
    }
    Page {
        name: "wishes"
        WishPage { anchors.fill: parent }
    }
    Page {
        name: "cards"
        BuildsPage { anchors.fill: parent; onOpenOptimizer: function(avatarId) { if (typeof optimizer !== "undefined") optimizer.setCharacter(avatarId); win.page = "optimizer" } }
    }
    Page {
        name: "optimizer"
        OptimizerPage { anchors.fill: parent }
    }

    UpdateBanner { }
}
