import QtQuick
import QtQuick.Layouts
import Lumenspar

// The launch screen: one tile per tool.
Item {
    id: menu
    signal open(string target)

    // The character event banner's stats, if any wishes have been imported.
    readonly property var characterBanner: {
        const list = wishes.banners
        for (let i = 0; i < list.length; i++)
            if (list[i].key === "character") return list[i]
        return null
    }

    component Tile: Rectangle {
        id: tile
        property string glyph
        property string title
        property string blurb
        property string detail
        property string target
        Layout.preferredWidth: Math.min(330, (menu.width - 140 - 28 * (grid.columns - 1)) / grid.columns)
        Layout.preferredHeight: grid.columns === 4 ? 300 : 268
        radius: Theme.radius + 4
        color: hover.hovered ? Theme.surfaceHi : Theme.surface
        border.width: 1
        border.color: hover.hovered ? Theme.accent : Theme.border
        Behavior on color { ColorAnimation { duration: Theme.ease } }
        Behavior on border.color { ColorAnimation { duration: Theme.ease } }
        scale: tap.pressed ? 0.985 : 1.0
        Behavior on scale { NumberAnimation { duration: 90 } }

        HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
        TapHandler { id: tap; onTapped: menu.open(tile.target) }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 28
            spacing: 12

            Item {
                Layout.preferredWidth: 64; Layout.preferredHeight: 64
                Glow {
                    anchors.centerIn: parent
                    width: 110; height: 110
                    color: Theme.accent
                    alpha: hover.hovered ? 0.45 : 0.25
                }
                Text {
                    anchors.centerIn: parent
                    text: tile.glyph
                    font.pixelSize: 42
                    color: Theme.accent
                }
            }
            Text {
                text: tile.title
                color: Theme.text
                font.pixelSize: 22
                font.weight: Font.DemiBold
            }
            Text {
                Layout.fillWidth: true
                text: tile.blurb
                color: Theme.textDim
                font.pixelSize: 13
                wrapMode: Text.WordWrap
            }
            Item { Layout.fillHeight: true }
            Text {
                Layout.fillWidth: true
                text: tile.detail
                visible: text !== ""
                color: Theme.accent
                font.pixelSize: 12
                wrapMode: Text.WordWrap
            }
        }
    }

    // Version, manual update check and the automatic-check switch.
    RowLayout {
        id: footer
        anchors.bottom: parent.bottom
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottomMargin: 16
        spacing: 16

        Text {
            text: "Lumenspar " + updates.currentVersion
            color: Theme.textDim
            font.pixelSize: 12
        }
        GhostButton {
            label: updates.state === "checking" ? "Checking…" : "Check for updates"
            enabledState: !updates.busy
            onClicked: updates.checkNow()
        }
        AccentButton {
            visible: updates.available && updates.state === "idle"
            label: updates.canInstall ? "Update to " + updates.latestVersion : "Get " + updates.latestVersion
            onClicked: updates.install()
        }
        Text {
            visible: text !== ""
            text: updates.status
            color: updates.available ? Theme.accent : Theme.textDim
            font.pixelSize: 12
            elide: Text.ElideRight
            Layout.maximumWidth: 360
        }
        Row {
            spacing: 8
            Layout.alignment: Qt.AlignVCenter
            Rectangle {
                width: 18; height: 18; radius: 5
                anchors.verticalCenter: parent.verticalCenter
                color: updates.autoCheck ? Theme.accent : "transparent"
                border.width: 1
                border.color: updates.autoCheck ? Theme.accent : Theme.border
                Text {
                    anchors.centerIn: parent
                    visible: updates.autoCheck
                    text: "✓"
                    color: "#08121A"
                    font.pixelSize: 13
                    font.weight: Font.Bold
                }
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "Check automatically"
                color: Theme.textDim
                font.pixelSize: 12
            }
            TapHandler { onTapped: updates.autoCheck = !updates.autoCheck }
            HoverHandler { cursorShape: Qt.PointingHandCursor }
        }
    }

    GridLayout {
        id: grid
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -18
        columns: menu.width >= 1480 ? 4 : 2
        columnSpacing: 28
        rowSpacing: 28

        Tile {
            glyph: "✧"
            title: "Wish Counter"
            blurb: "Pity, guarantees and 50/50 results for every banner, read from your in-game wish history."
            detail: menu.characterBanner
                    ? "Character Event: " + menu.characterBanner.pity5 + " pity"
                      + (menu.characterBanner.guaranteed ? " · guaranteed" : "")
                    : (wishes.totalWishes > 0 ? wishes.totalWishes + " wishes on record" : "")
            target: "wishes"
        }
        Tile {
            glyph: "❖"
            title: "Inventory Scanner"
            blurb: "Reads your artifacts, weapons, characters and materials off the screen into a .GOOD file for Genshin Optimizer and friends."
            detail: backend.scanning ? "Scan running…" : ""
            target: "scanner"
        }
        Tile {
            glyph: "✦"
            title: "Build Cards"
            blurb: "Akasha-style cards for every character in your profile showcase: talents, weapon, artifacts with roll counts, crit value and final stats."
            detail: cards.cards.length > 0 ? cards.cards.length + " characters collected" : ""
            target: "cards"
        }
        Tile {
            glyph: "◈"
            title: "Optimizer"
            blurb: "The best artifacts from your scan for any character: damage estimate, stat weights, targets or ratios, with conditional crit taken into account."
            detail: optimizer.pieceCount > 0 ? optimizer.pieceCount + " artifacts scanned" : ""
            target: "optimizer"
        }
    }
}
