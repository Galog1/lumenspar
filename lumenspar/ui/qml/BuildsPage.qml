import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Lumenspar

// Build cards: every character from the Enka.Network showcase as an
// Akasha-style card -- talents, weapon, artifacts with roll counts, crit
// value and final stats -- which can be saved as an image.
Item {
    id: page
    objectName: "buildsPage"

    property int selected: 0
    readonly property var card: cards.cards.length > 0
                                ? cards.cards[Math.min(selected, cards.cards.length - 1)] : null

    function elementColor(e) {
        switch (e) {
        case "pyro": return "#EF7938"
        case "hydro": return "#4CC2F1"
        case "anemo": return "#74C2A8"
        case "electro": return "#B08FC2"
        case "dendro": return "#A5C83B"
        case "cryo": return "#9FD6E3"
        case "geo": return "#FAB632"
        default: return Theme.accent
        }
    }

    function saveCard() {
        if (!page.card) return
        const name = page.card.name
        buildCard.grabToImage(function(result) {
            const path = cards.cardPath(name)
            cards.cardSaved(path, result.saveToFile(path))
        }, Qt.size(buildCard.width * 2, buildCard.height * 2))
    }

    // ── small pieces of the card ─────────────────────────────────────────
    component RollDots: Row {
        id: dotsRow
        property int rolls
        property color tint
        spacing: 3
        Repeater {
            model: Math.max(0, dotsRow.rolls)
            delegate: Rectangle { width: 5; height: 5; radius: 2.5; color: dotsRow.tint }
        }
    }

    component Art: Rectangle {      // an icon on a rarity-tinted tile, or a placeholder
        property string source
        property int rarity: 5
        property string fallback: ""
        radius: 10
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.darker(Theme.rarity(rarity), 2.6) }
            GradientStop { position: 1.0; color: Qt.darker(Theme.rarity(rarity), 1.5) }
        }
        Image {
            anchors.fill: parent
            anchors.margins: 3
            source: parent.source
            visible: status === Image.Ready
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            smooth: true
            mipmap: true
        }
        Text {
            anchors.centerIn: parent
            visible: parent.source === ""
            text: parent.fallback
            color: "#FFFFFF"
            opacity: 0.7
            font.pixelSize: parent.height * 0.32
            font.weight: Font.DemiBold
        }
    }

    // ── the card: a fixed 1160×600 layout, scaled to the page ───────────
    component BuildCard: Rectangle {
        id: bc
        property var c
        readonly property color tint: page.elementColor(c ? c.element : "")
        width: 1160
        height: 600
        radius: 20
        clip: true
        color: "#0D1119"
        border.width: 1
        border.color: Qt.rgba(tint.r, tint.g, tint.b, 0.35)

        // element wash behind everything
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Qt.rgba(bc.tint.r, bc.tint.g, bc.tint.b, 0.30) }
                GradientStop { position: 0.45; color: Qt.rgba(bc.tint.r, bc.tint.g, bc.tint.b, 0.06) }
                GradientStop { position: 1.0; color: Qt.rgba(bc.tint.r, bc.tint.g, bc.tint.b, 0.12) }
            }
        }

        // ── left: splash art, name, constellations, talents ──
        Item {
            id: left
            x: 0; y: 0
            width: 420; height: parent.height
            clip: true
            Image {   // pre-cut to this panel, rounded corners included (builds_backend)
                anchors.fill: parent
                anchors.margins: 1      // inside the card's border
                source: bc.c ? bc.c.splashUrl : ""
                fillMode: Image.Stretch
                asynchronous: true
                smooth: true
                mipmap: true
                opacity: status === Image.Ready ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 250 } }
            }
            Image {   // the portrait, until (or unless) the splash art is cached
                anchors.centerIn: parent
                anchors.verticalCenterOffset: -60
                width: 220; height: 220
                visible: bc.c !== null && bc.c.splashUrl === ""
                source: bc.c ? bc.c.iconUrl : ""
                fillMode: Image.PreserveAspectFit
                opacity: 0.85
            }
            Rectangle {   // fade into the card on the right and at the bottom
                anchors.fill: parent
                anchors.margins: 1
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.6; color: "transparent" }
                    GradientStop { position: 1.0; color: "#0D1119" }
                }
            }
            Rectangle {
                anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                anchors.leftMargin: 1; anchors.bottomMargin: 1
                height: 260
                bottomLeftRadius: bc.radius - 1
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "transparent" }
                    GradientStop { position: 0.55; color: Qt.rgba(0.05, 0.067, 0.1, 0.88) }
                    GradientStop { position: 1.0; color: "#0D1119" }
                }
            }

            ColumnLayout {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 24
                spacing: 8

                Text {
                    text: bc.c ? bc.c.name : ""
                    color: "#FFFFFF"
                    font.pixelSize: 34
                    font.weight: Font.Bold
                    style: Text.Raised
                    styleColor: Qt.rgba(0, 0, 0, 0.5)
                }
                Text {
                    text: bc.c ? "Lv. " + bc.c.level + " / " + bc.c.maxLevel + "   ·   Friendship " + bc.c.friendship : ""
                    color: "#E3E8F2"
                    font.pixelSize: 14
                }
                Row {   // constellations: C0 to C6
                    spacing: 6
                    Repeater {
                        model: 6
                        delegate: Rectangle {
                            required property int index
                            width: 22; height: 22; radius: 11
                            color: bc.c && index < bc.c.constellation
                                   ? bc.tint : Qt.rgba(1, 1, 1, 0.08)
                            border.width: 1
                            border.color: Qt.rgba(bc.tint.r, bc.tint.g, bc.tint.b, 0.6)
                            Text {
                                anchors.centerIn: parent
                                text: index + 1
                                font.pixelSize: 10
                                font.weight: Font.Bold
                                color: bc.c && index < bc.c.constellation ? "#0D1119" : "#8A94A9"
                            }
                        }
                    }
                    Text {
                        leftPadding: 6
                        anchors.verticalCenter: parent.verticalCenter
                        text: bc.c ? "C" + bc.c.constellation : ""
                        color: bc.tint
                        font.pixelSize: 16
                        font.weight: Font.Bold
                    }
                }
                Row {   // talents, with constellation bonuses marked
                    spacing: 10
                    topPadding: 4
                    Repeater {
                        model: bc.c ? bc.c.talents : []
                        delegate: Rectangle {
                            required property var modelData
                            width: 92; height: 46; radius: 12
                            color: Qt.rgba(0, 0, 0, 0.45)
                            border.width: 1
                            border.color: modelData.boosted ? bc.tint : Qt.rgba(1, 1, 1, 0.15)
                            Column {
                                anchors.centerIn: parent
                                spacing: 0
                                Text {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: modelData.slot === "auto" ? "Normal" : modelData.slot === "skill" ? "Skill" : "Burst"
                                    color: "#8A94A9"
                                    font.pixelSize: 10
                                }
                                Text {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: modelData.level
                                    color: modelData.boosted ? bc.tint : "#FFFFFF"
                                    font.pixelSize: 18
                                    font.weight: Font.Bold
                                }
                            }
                        }
                    }
                }
            }
        }

        // ── middle: weapon, final stats, crit value, sets ──
        ColumnLayout {
            x: 420; y: 24
            width: 330
            spacing: 14

            RowLayout {   // weapon
                Layout.fillWidth: true
                spacing: 12
                Art {
                    Layout.preferredWidth: 72; Layout.preferredHeight: 72
                    source: bc.c && bc.c.weapon ? bc.c.weapon.iconUrl : ""
                    rarity: bc.c && bc.c.weapon ? bc.c.weapon.rarity : 1
                    fallback: "⚔"
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Text {
                        Layout.fillWidth: true
                        text: bc.c && bc.c.weapon ? bc.c.weapon.name : "No weapon"
                        color: "#FFFFFF"
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }
                    Text {
                        text: bc.c && bc.c.weapon
                              ? "Lv. " + bc.c.weapon.level + (bc.c.weapon.refinement > 0 ? "   R" + bc.c.weapon.refinement : "")
                              : ""
                        color: Theme.rarity(bc.c && bc.c.weapon ? bc.c.weapon.rarity : 1)
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                    }
                    Text {
                        Layout.fillWidth: true
                        text: bc.c && bc.c.weapon
                              ? bc.c.weapon.stats.map(function(s) { return s.label + " " + s.text }).join("   ·   ")
                              : ""
                        color: "#B9C2D3"
                        font.pixelSize: 12
                        elide: Text.ElideRight
                    }
                }
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: Qt.rgba(1, 1, 1, 0.08) }

            ColumnLayout {   // final stats
                Layout.fillWidth: true
                spacing: 7
                Repeater {
                    model: bc.c ? bc.c.stats : []
                    delegate: RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        Text { text: modelData.label; color: "#B9C2D3"; font.pixelSize: 14 }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: modelData.text
                            color: "#FFFFFF"
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                        }
                    }
                }
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: Qt.rgba(1, 1, 1, 0.08) }

            RowLayout {
                Layout.fillWidth: true
                Text { text: "Crit Value"; color: "#B9C2D3"; font.pixelSize: 14 }
                Item { Layout.fillWidth: true }
                Text {
                    text: bc.c ? bc.c.critValue.toFixed(1) : ""
                    color: bc.tint
                    font.pixelSize: 24
                    font.weight: Font.Bold
                }
            }

            Repeater {   // set bonuses in effect
                model: bc.c ? bc.c.sets : []
                delegate: RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 8
                    Rectangle {
                        width: 28; height: 22; radius: 6
                        color: Qt.rgba(bc.tint.r, bc.tint.g, bc.tint.b, 0.2)
                        Text {
                            anchors.centerIn: parent
                            text: modelData.count >= 4 ? "4" : "2"
                            color: bc.tint
                            font.pixelSize: 12
                            font.weight: Font.Bold
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: modelData.name
                        color: "#E3E8F2"
                        font.pixelSize: 13
                        elide: Text.ElideRight
                    }
                }
            }
        }

        // ── right: the five artifacts ──
        Column {
            x: 770; y: 14
            width: 376
            spacing: 6
            Repeater {
                model: bc.c ? bc.c.artifacts : []
                delegate: Rectangle {
                    required property var modelData
                    width: 376; height: 108
                    radius: 12
                    color: Qt.rgba(0, 0, 0, 0.32)
                    border.width: 1
                    border.color: Qt.rgba(1, 1, 1, 0.06)

                    Art {
                        x: 10; y: 10
                        width: 58; height: 58
                        source: modelData.iconUrl
                        rarity: modelData.rarity
                        fallback: modelData.slot.charAt(0).toUpperCase()
                    }
                    Text {
                        x: 10; y: 74
                        width: 58
                        horizontalAlignment: Text.AlignHCenter
                        text: "+" + modelData.level
                        color: "#B9C2D3"
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                    Column {
                        x: 80; y: 10
                        width: 120
                        spacing: 2
                        Text {
                            width: parent.width
                            text: modelData.main.label
                            color: "#B9C2D3"
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                        Text {
                            text: modelData.main.text
                            color: "#FFFFFF"
                            font.pixelSize: 20
                            font.weight: Font.Bold
                        }
                        Text {
                            width: parent.width
                            topPadding: 4
                            text: "CV " + modelData.critValue.toFixed(1)
                            color: bc.tint
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                        }
                        Text {
                            width: parent.width
                            text: modelData.setName
                            color: "#6F7A90"
                            font.pixelSize: 10
                            elide: Text.ElideRight
                        }
                    }
                    Grid {   // substats, each with one dot per roll
                        x: 206; y: 12
                        columns: 1
                        rowSpacing: 4
                        Repeater {
                            model: modelData.subs
                            delegate: Item {
                                required property var modelData
                                width: 160; height: 19
                                Text {
                                    anchors.left: parent.left
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 96
                                    text: modelData.label.replace("Elemental Mastery", "EM").replace("Energy Recharge", "ER")
                                    color: modelData.key === "critRate_" || modelData.key === "critDMG_" ? "#FFFFFF" : "#B9C2D3"
                                    font.pixelSize: 12
                                    elide: Text.ElideRight
                                }
                                Text {
                                    anchors.right: dots.left
                                    anchors.rightMargin: 6
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: modelData.text
                                    color: "#FFFFFF"
                                    font.pixelSize: 12
                                    font.weight: Font.DemiBold
                                }
                                RollDots {
                                    id: dots
                                    anchors.right: parent.right
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 38
                                    layoutDirection: Qt.RightToLeft
                                    rolls: modelData.rolls
                                    tint: modelData.key === "critRate_" || modelData.key === "critDMG_"
                                          ? bc.tint : "#6F7A90"
                                }
                            }
                        }
                    }
                }
            }
        }

        Text {   // whose build this is
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 10
            text: (cards.player.nickname ? cards.player.nickname + " · " : "")
                  + (cards.account ? "UID " + cards.account + " · " : "") + "Lumenspar"
            color: "#4A5468"
            font.pixelSize: 10
        }
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
            }

            Text {
                Layout.fillWidth: true
                Layout.topMargin: 40
                visible: cards.cards.length === 0
                horizontalAlignment: Text.AlignHCenter
                text: "No builds yet. Enter your UID and fetch your showcase."
                color: Theme.textDim
                font.pixelSize: 14
            }

            Flow {   // one chip per collected character
                Layout.fillWidth: true
                spacing: 10
                visible: cards.cards.length > 0
                Repeater {
                    model: cards.cards
                    delegate: Rectangle {
                        id: chip
                        required property var modelData
                        required property int index
                        readonly property bool current: index === Math.min(page.selected, cards.cards.length - 1)
                        readonly property color tint: page.elementColor(modelData.element)
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

                        Art {
                            anchors.horizontalCenter: parent.horizontalCenter
                            y: 8
                            width: 58; height: 58
                            radius: 29
                            source: chip.modelData.iconUrl
                            rarity: chip.modelData.rarity
                            fallback: chip.modelData.name.charAt(0)
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

            Item {   // the card, scaled down to fit narrower windows
                id: holder
                Layout.fillWidth: true
                visible: page.card !== null
                readonly property real fit: Math.min(1, width / buildCard.width)
                Layout.preferredHeight: buildCard.height * fit
                BuildCard {
                    id: buildCard
                    c: page.card
                    transformOrigin: Item.TopLeft
                    scale: holder.fit
                }
            }

            RowLayout {
                Layout.fillWidth: true
                visible: page.card !== null
                spacing: 10
                AccentButton { label: "Save card as image"; onClicked: page.saveCard() }
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
