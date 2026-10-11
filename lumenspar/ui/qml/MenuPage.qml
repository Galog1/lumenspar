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
        Layout.preferredWidth: 360
        Layout.preferredHeight: 300
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

    RowLayout {
        anchors.centerIn: parent
        spacing: 28

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
    }
}
