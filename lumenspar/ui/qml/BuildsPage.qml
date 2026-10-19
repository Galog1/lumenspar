import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import Lumenspar

// Build cards: every character from the Enka.Network showcase and HoYoLAB as
// an Akasha-style card -- talents, weapon, artifacts with roll counts, crit or
// roll value and final stats -- which can be saved as an image.
Item {
    id: page
    objectName: "buildsPage"

    property int selected: 0
    signal openOptimizer(string avatarId)
    readonly property var card: {
        const rev = cards.revision          // re-read when the cards change
        return cards.count > 0 ? cards.cardAt(Math.min(selected, cards.count - 1)) : null
    }
    // The card on screen gets its art first, ahead of the rest of the collection.
    onCardChanged: if (card) cards.prefer(card.avatarId)

    function saveCard() {
        if (!page.card) return
        saveDlg.currentFile = cards.defaultCardFile(page.card.name)
        saveDlg.open()
    }

    FileDialog {
        id: saveDlg
        title: "Save card as image"
        fileMode: FileDialog.SaveFile
        nameFilters: ["PNG image (*.png)"]
        defaultSuffix: "png"
        onAccepted: {
            const path = cards.chosenCardPath(selectedFile.toString())
            buildCard.grabToImage(function(result) {
                cards.cardSaved(path, result.saveToFile(path))
            }, Qt.size(buildCard.width * 2, buildCard.height * 2))
        }
    }

    // The HoYoLAB sign-in window exists only while it is open, so the embedded
    // browser (and its in-memory session) is created and destroyed with it.
    Loader {
        objectName: "hoyolabLoader"
        active: hoyolab.open
        source: "HoyolabWindow.qml"
    }

    ScrollView {
        id: scroll
        anchors.fill: parent
        anchors.margins: 20
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            width: scroll.availableWidth
            spacing: 18

            Card {
                title: "Showcase"
                subtitle: "Reads the characters in your in-game profile showcase through Enka.Network. Turn on \"Show Character Details\" in your profile. To add more characters, swap them into the showcase, wait for the game to publish it (leaving to the title screen and back is fastest), then fetch again: Lumenspar keeps every character it has seen."

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    TextField {
                        id: uidField
                        Layout.preferredWidth: 200
                        text: backend.uid
                        placeholderText: "UID"
                        placeholderTextColor: Theme.textDim
                        inputMethodHints: Qt.ImhDigitsOnly
                        validator: RegularExpressionValidator { regularExpression: /[0-9]{0,12}/ }
                        color: Theme.text
                        font.pixelSize: 14
                        selectByMouse: true
                        onEditingFinished: backend.uid = text
                        onAccepted: cards.fetch(text)
                        background: Rectangle {
                            radius: 8; color: Theme.bgAlt
                            border.color: uidField.activeFocus ? Theme.accent : Theme.border
                            border.width: 1
                        }
                    }
                    AccentButton {
                        label: cards.busy ? "Reading…" : cards.waitSeconds > 0 && cards.account === uidField.text
                               ? "Refresh in " + cards.waitSeconds + "s" : "Fetch showcase"
                        pulsing: cards.busy
                        enabledState: !cards.busy && uidField.text !== ""
                                      && !(cards.waitSeconds > 0 && cards.account === uidField.text)
                        onClicked: { backend.uid = uidField.text; cards.fetch(uidField.text) }
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        visible: cards.player.nickname !== undefined && cards.player.nickname !== ""
                        text: (cards.player.nickname || "") + "  ·  AR " + (cards.player.level || 0)
                              + "  ·  WL " + (cards.player.worldLevel || 0)
                              + (cards.player.achievements ? "  ·  " + cards.player.achievements + " achievements" : "")
                              + (cards.player.abyss ? "  ·  Abyss " + cards.player.abyss : "")
                        color: Theme.textDim
                        font.pixelSize: 12
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: cards.status
                    visible: text !== ""
                    color: Theme.textDim
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }

                Text {
                    Layout.fillWidth: true
                    text: cards.akashaStatus
                    visible: text !== ""
                    color: Theme.textDim
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
            }

            Card {
                title: "All characters"
                subtitle: "The showcase holds only a few characters. HoYoLAB lists every character on your account with its weapon and artifacts, but it only answers to a signed-in account: Lumenspar opens a window where you sign in to HoYoLAB yourself. Your password goes to HoYoLAB only, and nothing about the sign-in is saved or sent anywhere else; closing the window forgets it. Characters with the same build in both sources keep the showcase's exact stats. You do not need to enter your UID first: Lumenspar looks up your Genshin account after you sign in (if it cannot, it will ask for the UID)."

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    GhostButton {
                        id: hoyoButton
                        label: hoyolab.open ? "Window open…" : "Sign in to HoYoLAB"
                        // Stays clickable without a UID: begin() answers with what
                        // is missing, shown beside the button, instead of the button
                        // looking broken.
                        enabledState: hoyolab.available && !hoyolab.open
                        onClicked: {
                            if (uidField.text !== "")
                                backend.uid = uidField.text
                            hoyoNote.text = hoyolab.begin(uidField.text)
                        }
                    }
                    Text {
                        id: hoyoNote
                        Layout.fillWidth: true
                        text: hoyolab.available ? "" : "The embedded browser is not part of this install."
                        color: Theme.textDim
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                Layout.topMargin: 40
                visible: cards.count === 0
                horizontalAlignment: Text.AlignHCenter
                text: "No builds yet. Enter your UID and fetch your showcase."
                color: Theme.textDim
                font.pixelSize: 14
            }

            Flickable {   // the characters: a short strip that scrolls, so the card stays in reach
                id: strip
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(chips.height, 236)
                visible: cards.count > 0
                contentWidth: width
                contentHeight: chips.height
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: chips.height > 236 ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff }

                // keep the chosen character in view when the selection moves
                Connections {
                    target: page
                    function onSelectedChanged() {
                        const row = Math.floor(page.selected / Math.max(1, Math.floor((strip.width + 10) / 88)))
                        const top = row * 106
                        if (top < strip.contentY) strip.contentY = top
                        else if (top + 96 > strip.contentY + strip.height) strip.contentY = top + 96 - strip.height
                    }
                }

                Flow {   // one chip per collected character
                    id: chips
                    width: strip.width - 14
                    spacing: 10
                    Repeater {
                        model: cards.chips
                        delegate: Rectangle {
                            id: chip
                            required property var modelData
                            required property int index
                            readonly property bool current: index === Math.min(page.selected, cards.count - 1)
                            readonly property color tint: Theme.element(modelData.element)
                            width: 78; height: 96
                            radius: 14
                            color: current ? Qt.rgba(tint.r, tint.g, tint.b, 0.18) : Theme.surface
                            border.width: current ? 2 : 1
                            border.color: current ? tint : Theme.border
                            opacity: modelData.inShowcase || current ? 1.0 : 0.75

                            HoverHandler { id: chipHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: page.selected = chip.index }
                            ToolTip.visible: chipHover.hovered
                            ToolTip.delay: 400
                            ToolTip.text: modelData.name + " · C" + modelData.constellation
                                          + "\nLast read " + modelData.fetched
                                          + (modelData.inShowcase ? "" : " (not in the latest showcase)")

                            Rectangle {
                                anchors.horizontalCenter: parent.horizontalCenter
                                y: 8
                                width: 58; height: 58
                                radius: 29
                                gradient: Gradient {
                                    GradientStop { position: 0.0; color: Qt.darker(Theme.rarity(chip.modelData.rarity), 2.6) }
                                    GradientStop { position: 1.0; color: Qt.darker(Theme.rarity(chip.modelData.rarity), 1.5) }
                                }
                                Image {
                                    anchors.fill: parent
                                    anchors.margins: 3
                                    source: chip.modelData.iconUrl
                                    sourceSize: Qt.size(116, 116)
                                    visible: status === Image.Ready
                                    fillMode: Image.PreserveAspectFit
                                    asynchronous: true
                                    smooth: true
                                    mipmap: true
                                }
                                Text {
                                    anchors.centerIn: parent
                                    visible: chip.modelData.iconUrl === ""
                                    text: chip.modelData.name.charAt(0)
                                    color: "#FFFFFF"
                                    opacity: 0.7
                                    font.pixelSize: 18
                                    font.weight: Font.DemiBold
                                }
                            }
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                y: 70
                                width: parent.width - 8
                                horizontalAlignment: Text.AlignHCenter
                                text: chip.modelData.name
                                color: Theme.text
                                font.pixelSize: 11
                                elide: Text.ElideRight
                            }
                        }
                    }
                }
            }

            Item {   // the card, scaled down to fit narrower windows
                id: holder
                Layout.fillWidth: true
                visible: page.card !== null
                readonly property real fit: Math.min(1, width / buildCard.width)
                Layout.preferredHeight: buildCard.height * fit
                BuildCard {
                    id: buildCard
                    c: page.card
                    metric: cards.cardMetric
                    footer: (cards.player.nickname ? cards.player.nickname + " · " : "")
                            + (cards.account ? "UID " + cards.account + " · " : "") + "Lumenspar"
                    transformOrigin: Item.TopLeft
                    scale: holder.fit
                }
            }

            RowLayout {
                Layout.fillWidth: true
                visible: page.card !== null
                spacing: 10
                AccentButton { label: "Save card as image"; onClicked: page.saveCard() }
                GhostButton { label: "Optimize"; onClicked: if (page.card) page.openOptimizer(page.card.avatarId) }
                Text { text: "Artifact score"; color: Theme.textDim; font.pixelSize: 12 }
                Segmented {   // CV: crit stats only. RV: every substat the build uses, in rolls.
                    options: [{ value: "cv", label: "CV" }, { value: "rv", label: "RV" }]
                    current: cards.cardMetric
                    onPicked: (value) => cards.setCardMetric(value)
                }
                Text {
                    Layout.fillWidth: true
                    text: page.card ? "Read " + page.card.fetched + (page.card.inShowcase ? "" : " · not in the latest showcase") : ""
                    color: Theme.textDim
                    font.pixelSize: 12
                }
                GhostButton {
                    label: "Remove from collection"
                    onClicked: if (page.card) cards.forget(page.card.avatarId)
                }
            }

            Item { Layout.preferredHeight: 4 }
        }
    }
}
