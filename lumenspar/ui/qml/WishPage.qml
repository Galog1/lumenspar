import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import Lumenspar

// The wish counter: import the wish history, then one card per banner with
// pity, guarantee and 50/50 results (modelled on paimon.moe's counter).
Item {
    id: page
    objectName: "wishPage"

    function resultColour(r) {
        return r === "won" ? Theme.ok : r === "lost" ? Theme.danger
             : r === "guaranteed" ? Theme.accent : Theme.textDim
    }

    // ── a pity meter: count over the hard pity, with a bar ──────────────
    component PityMeter: ColumnLayout {
        property string label
        property int value
        property int maximum
        property color tint
        spacing: 6
        Layout.fillWidth: true
        Text { text: parent.label; color: Theme.textDim; font.pixelSize: 12 }
        Row {
            spacing: 4
            Text { text: value; color: Theme.text; font.pixelSize: 30; font.weight: Font.DemiBold }
            Text {
                text: "/ " + maximum
                color: Theme.textDim
                font.pixelSize: 14
                anchors.baseline: parent.children[0].baseline
            }
        }
        Rectangle {
            Layout.fillWidth: true
            height: 6; radius: 3
            color: Qt.rgba(1, 1, 1, 0.06)
            Rectangle {
                width: parent.width * Math.min(1, value / Math.max(1, maximum))
                height: parent.height; radius: 3
                color: tint
                Behavior on width { NumberAnimation { duration: 300 } }
            }
        }
    }

    // ── one banner ─────────────────────────────────────────────────────
    component BannerCard: Card {
        id: card
        required property var modelData
        readonly property var b: modelData
        title: b.label
        subtitle: b.total.toLocaleString(Qt.locale(), "f", 0) + " wishes · "
                  + b.primogems.toLocaleString(Qt.locale(), "f", 0) + " primogems"
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignTop

        RowLayout {
            Layout.fillWidth: true
            spacing: 24
            PityMeter { label: "5★ pity"; value: card.b.pity5; maximum: card.b.hardPity; tint: Theme.rarity(5) }
            PityMeter { label: "4★ pity"; value: card.b.pity4; maximum: 10; tint: Theme.rarity(4) }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            visible: card.b.hasFiftyFifty
            Rectangle {
                radius: 8
                implicitHeight: 26
                implicitWidth: guaranteeText.implicitWidth + 20
                color: card.b.guaranteed ? Qt.rgba(0.31, 0.85, 0.91, 0.14) : Qt.rgba(1, 1, 1, 0.05)
                border.width: 1
                border.color: card.b.guaranteed ? Theme.accent : Theme.border
                Text {
                    id: guaranteeText
                    anchors.centerIn: parent
                    text: card.b.guaranteed ? "Next 5★ guaranteed featured" : "Next 5★ is a 50/50"
                    color: card.b.guaranteed ? Theme.accent : Theme.textDim
                    font.pixelSize: 12
                }
            }
            Text {
                text: "50/50: won " + card.b.won + " · lost " + card.b.lost
                color: Theme.textDim
                font.pixelSize: 12
            }
            Item { Layout.fillWidth: true }
        }

        Text {
            Layout.fillWidth: true
            text: "5★ ×" + card.b.fiveCount + " · 4★ ×" + card.b.fourCount
                  + (card.b.fiveCount > 0 ? " · average 5★ pity " + card.b.averagePity : "")
            color: Theme.textDim
            font.pixelSize: 12
        }

        Text {
            Layout.fillWidth: true
            visible: card.b.scheduleStale
            text: "A 5★ is newer than the banner data, so its 50/50 result (and the guarantee) is unknown. Updating Lumenspar's game data fixes this."
            color: Theme.danger
            font.pixelSize: 12
            wrapMode: Text.WordWrap
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4
            visible: card.b.fives.length > 0
            Text { text: "5★ history"; color: Theme.text; font.pixelSize: 13; font.weight: Font.DemiBold }
            Repeater {
                model: card.b.fives
                delegate: RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 10
                    Text {
                        text: modelData.name
                        color: Theme.rarity(5)
                        font.pixelSize: 13
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                    }
                    Text { text: modelData.time.substring(0, 10); color: Theme.textDim; font.pixelSize: 11 }
                    Text {
                        text: modelData.pity
                        color: Theme.text
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        horizontalAlignment: Text.AlignRight
                        Layout.preferredWidth: 28
                    }
                    Text {
                        text: modelData.result
                        visible: modelData.result !== ""
                        color: page.resultColour(modelData.result)
                        font.pixelSize: 11
                        Layout.preferredWidth: 72
                    }
                }
            }
        }
    }

    ScrollView {
        id: scroll
        anchors.fill: parent
        anchors.margins: 20
        contentWidth: availableWidth
        clip: true
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        ColumnLayout {
            width: scroll.availableWidth
            spacing: 18

            Card {
                title: "Import wish history"
                subtitle: "Open the wish history in-game (Wish → History), then import. That leaves a link behind for about a day; Lumenspar keeps every wish it has imported, so importing again later only adds the new ones."

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    AccentButton {
                        label: wishes.busy ? "Stop" : "Import from game"
                        pulsing: wishes.busy
                        onClicked: wishes.busy ? wishes.stop() : wishes.importFromGame()
                    }
                    GhostButton {
                        label: "Choose game folder…"
                        enabledState: !wishes.busy
                        onClicked: gameFolderDialog.open()
                    }
                    Item { Layout.fillWidth: true }
                    GhostButton {
                        label: "Copy link for paimon.moe"
                        enabledState: !wishes.busy
                        onClicked: wishes.copyPaimonLink()
                    }
                }

                // The link paimon.moe's own script would produce, once found.
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    visible: wishes.paimonLink !== ""
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        TextField {
                            id: paimonField
                            Layout.fillWidth: true
                            text: wishes.paimonLink
                            readOnly: true
                            selectByMouse: true
                            color: Theme.text
                            font.pixelSize: 12
                            font.family: "monospace"
                            background: Rectangle {
                                radius: 8; color: Theme.bgAlt
                                border.color: Theme.border; border.width: 1
                            }
                        }
                        GhostButton { label: "Copy again"; onClicked: wishes.copyPaimonLinkAgain() }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "Paste this into paimon.moe's wish import. Treat it like a password: until it expires, anyone who has it can read your wish history."
                        color: Theme.textDim
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    TextField {
                        id: linkField
                        Layout.fillWidth: true
                        placeholderText: "…or paste a wish history link"
                        placeholderTextColor: Theme.textDim
                        color: Theme.text
                        font.pixelSize: 13
                        selectByMouse: true
                        background: Rectangle {
                            radius: 8; color: Theme.bgAlt
                            border.color: linkField.activeFocus ? Theme.accent : Theme.border
                            border.width: 1
                        }
                    }
                    GhostButton {
                        label: "Use link"
                        enabledState: !wishes.busy && linkField.text.trim() !== ""
                        onClicked: { wishes.importFromLink(linkField.text); linkField.text = "" }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: wishes.status
                    visible: text !== ""
                    color: Theme.textDim
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 120
                    visible: wishLog.text !== ""
                    radius: 10
                    color: Theme.bg
                    border.color: Theme.border
                    border.width: 1
                    ScrollView {
                        id: wishLogScroll
                        anchors.fill: parent
                        anchors.margins: 10
                        clip: true
                        TextArea {
                            id: wishLog
                            readOnly: true
                            selectByMouse: true
                            wrapMode: TextEdit.WrapAnywhere
                            color: Theme.textDim
                            font.family: "monospace"
                            font.pixelSize: 12
                            padding: 0
                            background: null
                        }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                visible: wishes.account !== ""
                text: "UID " + wishes.account + " · " + wishes.totalWishes.toLocaleString(Qt.locale(), "f", 0)
                      + " wishes on record" + (wishes.updated ? " · last imported " + wishes.updated : "")
                color: Theme.textDim
                font.pixelSize: 12
            }

            Text {
                Layout.fillWidth: true
                Layout.topMargin: 40
                visible: wishes.banners.length === 0
                horizontalAlignment: Text.AlignHCenter
                text: "No wishes imported yet."
                color: Theme.textDim
                font.pixelSize: 14
            }

            GridLayout {
                Layout.fillWidth: true
                columns: scroll.availableWidth > 900 ? 2 : 1
                columnSpacing: 18
                rowSpacing: 18
                Repeater {
                    model: wishes.banners
                    delegate: BannerCard {}
                }
            }

            Item { Layout.preferredHeight: 4 }
        }
    }

    FolderDialog {
        id: gameFolderDialog
        title: "Choose the Genshin Impact game folder"
        onAccepted: wishes.importFromFolder(selectedFolder.toString())
    }

    Connections {
        target: wishes
        function onLogAppended(line) {
            wishLog.append(line)
            Qt.callLater(function() {
                const bar = wishLogScroll.ScrollBar.vertical
                bar.position = Math.max(0, 1 - bar.size)
            })
        }
    }
}
