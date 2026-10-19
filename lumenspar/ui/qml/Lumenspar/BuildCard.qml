import QtQuick
import QtQuick.Layouts
import Lumenspar

// One build card: a fixed 1200x640 layout for a character from the build cards
// collection (see BuildsPage). The whole background -- splash art, halo, rings
// and the quiet area behind the stats -- is one baked image (cardart.py, c.bgUrl),
// so nothing here needs rounded clipping or shader effects. Everything sits on a
// 32px margin; `metric` picks whether artifacts show CV or RV.
Rectangle {
    id: bc
    property var c
    property string footer: ""
    property string metric: "cv"            // "cv" (crit value) | "rv" (roll value)
    readonly property bool rv: metric === "rv"
    readonly property color tint: Theme.element(c ? c.element : "")

    width: 1200
    height: 640
    color: "#0A0E16"

    // ── small pieces of the card ─────────────────────────────────────────
    component RollDots: Row {
        id: dotsRow
        property int rolls
        property color tint
        spacing: 2.5
        Repeater {
            model: Math.max(0, dotsRow.rolls)
            delegate: Rectangle { width: 5; height: 5; radius: 2.5; color: dotsRow.tint }
        }
    }

    component Art: Rectangle {      // an icon on a rarity-tinted tile, or a placeholder
        property string source
        property int rarity: 5
        property string fallback: ""
        radius: 12
        border.width: 1
        border.color: Qt.rgba(Qt.color(Theme.rarity(rarity)).r, Qt.color(Theme.rarity(rarity)).g,
                              Qt.color(Theme.rarity(rarity)).b, 0.55)
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.darker(Theme.rarity(rarity), 2.8) }
            GradientStop { position: 1.0; color: Qt.darker(Theme.rarity(rarity), 1.6) }
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

    component Panel: Rectangle {    // a dark glass block the stats sit on
        radius: 14
        color: Qt.rgba(0.03, 0.045, 0.075, 0.62)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.07)
    }

    // ── backdrop ─────────────────────────────────────────────────────────
    Rectangle {     // until the baked backdrop exists: an element wash and the portrait
        anchors.fill: parent
        visible: !bc.c || bc.c.bgUrl === ""
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: Qt.rgba(bc.tint.r, bc.tint.g, bc.tint.b, 0.34) }
            GradientStop { position: 0.5; color: Qt.rgba(bc.tint.r, bc.tint.g, bc.tint.b, 0.06) }
            GradientStop { position: 1.0; color: Qt.rgba(bc.tint.r, bc.tint.g, bc.tint.b, 0.12) }
        }
        Image {
            x: 90; y: 90
            width: 250; height: 250
            source: bc.c ? bc.c.iconUrl : ""
            fillMode: Image.PreserveAspectFit
            opacity: 0.9
        }
    }
    Image {
        anchors.fill: parent
        source: bc.c ? bc.c.bgUrl : ""
        fillMode: Image.Stretch
        asynchronous: true
        smooth: true
        opacity: status === Image.Ready ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 250 } }
    }

    // ── left: who this is ────────────────────────────────────────────────
    ColumnLayout {
        x: 32
        width: 372
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 34
        spacing: 9

        RowLayout {     // element and rarity
            spacing: 10
            Rectangle {
                implicitWidth: elementText.implicitWidth + 20
                implicitHeight: 24
                radius: 12
                color: Qt.rgba(0.03, 0.045, 0.075, 0.74)
                border.width: 1
                border.color: Qt.rgba(bc.tint.r, bc.tint.g, bc.tint.b, 0.7)
                Text {
                    id: elementText
                    anchors.centerIn: parent
                    text: bc.c ? bc.c.element.toUpperCase() : ""
                    color: bc.tint
                    font.pixelSize: 11
                    font.weight: Font.Bold
                    font.letterSpacing: 1.4
                }
            }
            Text {
                text: bc.c ? "★".repeat(bc.c.rarity) : ""
                color: Theme.rarity(bc.c ? bc.c.rarity : 5)
                font.pixelSize: 14
            }
        }
        Text {
            Layout.fillWidth: true
            text: bc.c ? bc.c.name : ""
            color: "#FFFFFF"
            font.pixelSize: 46
            font.weight: Font.Bold
            elide: Text.ElideRight
            style: Text.Raised
            styleColor: Qt.rgba(0, 0, 0, 0.55)
        }
        Text {
            Layout.fillWidth: true
            text: bc.c ? "Lv. " + bc.c.level + " / " + bc.c.maxLevel
                         + (bc.c.friendship > 0 ? "   ·   Friendship " + bc.c.friendship : "") : ""
            color: "#DCE3F0"
            font.pixelSize: 15
            elide: Text.ElideRight
        }
        Row {           // constellations: C0 to C6
            spacing: 7
            Repeater {
                model: 6
                delegate: Rectangle {
                    required property int index
                    width: 26; height: 26; radius: 13
                    color: bc.c && index < bc.c.constellation ? bc.tint : Qt.rgba(1, 1, 1, 0.07)
                    border.width: 1
                    border.color: Qt.rgba(bc.tint.r, bc.tint.g, bc.tint.b, 0.65)
                    Text {
                        anchors.centerIn: parent
                        text: index + 1
                        font.pixelSize: 11
                        font.weight: Font.Bold
                        color: bc.c && index < bc.c.constellation ? "#0A0E16" : "#8A94A9"
                    }
                }
            }
            Text {
                leftPadding: 6
                anchors.verticalCenter: parent.verticalCenter
                text: bc.c ? "C" + bc.c.constellation : ""
                color: bc.tint
                font.pixelSize: 20
                font.weight: Font.Bold
            }
        }
        Row {           // talents, with constellation bonuses marked
            spacing: 10
            topPadding: 4
            Repeater {
                model: bc.c ? bc.c.talents : []
                delegate: Rectangle {
                    required property var modelData
                    width: 112; height: 52; radius: 13
                    color: Qt.rgba(0.03, 0.045, 0.075, 0.68)
                    border.width: 1
                    border.color: modelData.boosted ? bc.tint : Qt.rgba(1, 1, 1, 0.16)
                    Column {
                        anchors.centerIn: parent
                        spacing: 0
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: modelData.slot === "auto" ? "Normal" : modelData.slot === "skill" ? "Skill" : "Burst"
                            color: "#9AA4B8"
                            font.pixelSize: 11
                        }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: modelData.level
                            color: modelData.boosted ? bc.tint : "#FFFFFF"
                            font.pixelSize: 21
                            font.weight: Font.Bold
                        }
                    }
                }
            }
        }
    }

    // ── middle: weapon, stats, the metric, sets ──────────────────────────
    ColumnLayout {
        x: 436; y: 34
        width: 352
        spacing: 10

        Panel {         // weapon
            Layout.fillWidth: true
            implicitHeight: 100
            RowLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 14
                Art {
                    Layout.preferredWidth: 72; Layout.preferredHeight: 72
                    source: bc.c && bc.c.weapon ? bc.c.weapon.iconUrl : ""
                    rarity: bc.c && bc.c.weapon ? bc.c.weapon.rarity : 1
                    fallback: "⚔"
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    Text {
                        Layout.fillWidth: true
                        text: bc.c && bc.c.weapon ? bc.c.weapon.name : "No weapon"
                        color: "#FFFFFF"
                        font.pixelSize: 16
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
                    Repeater {
                        model: bc.c && bc.c.weapon ? bc.c.weapon.stats : []
                        delegate: Text {
                            required property var modelData
                            Layout.fillWidth: true
                            text: modelData.label + "  " + modelData.text
                            color: "#B9C2D3"
                            font.pixelSize: 12
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }

        Panel {         // final stats
            Layout.fillWidth: true
            implicitHeight: statsColumn.implicitHeight + 28
            ColumnLayout {
                id: statsColumn
                anchors.fill: parent
                anchors.margins: 14
                spacing: 0
                Repeater {
                    model: bc.c ? bc.c.stats : []
                    delegate: RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredHeight: 26
                        Text {
                            text: modelData.label
                            color: modelData.key === "critRate_" || modelData.key === "critDMG_" ? "#E6ECF8" : "#A9B3C6"
                            font.pixelSize: 13
                        }
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
        }

        Panel {         // the metric: crit value or roll value of the whole build
            Layout.fillWidth: true
            implicitHeight: 84
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16; anchors.rightMargin: 16
                spacing: 14
                ColumnLayout {
                    spacing: 0
                    Text {
                        text: bc.rv ? "ROLL VALUE" : "CRIT VALUE"
                        color: "#9AA4B8"
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                        font.letterSpacing: 1.2
                    }
                    Text {
                        text: bc.c ? (bc.rv ? bc.c.rollText : bc.c.cvText) : ""
                        color: bc.tint
                        font.pixelSize: 36
                        font.weight: Font.Bold
                    }
                }
                Text {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    horizontalAlignment: Text.AlignRight
                    wrapMode: Text.WordWrap
                    maximumLineCount: 3
                    elide: Text.ElideRight
                    text: !bc.c ? "" : bc.rv
                          ? "Share of a perfect roll, counting " + bc.c.rvLabels
                          : "CRIT Rate × 2 + CRIT DMG, from every artifact substat"
                    color: "#7E889D"
                    font.pixelSize: 11
                }
            }
        }

        Repeater {      // set bonuses in effect
            model: bc.c ? bc.c.sets : []
            delegate: RowLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: 10
                Rectangle {
                    Layout.preferredWidth: 30; Layout.preferredHeight: 24
                    radius: 7
                    color: Qt.rgba(bc.tint.r, bc.tint.g, bc.tint.b, 0.22)
                    border.width: 1
                    border.color: Qt.rgba(bc.tint.r, bc.tint.g, bc.tint.b, 0.55)
                    Text {
                        anchors.centerIn: parent
                        text: modelData.count >= 4 ? "4" : "2"
                        color: bc.tint
                        font.pixelSize: 13
                        font.weight: Font.Bold
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: modelData.name
                    color: "#E3E8F2"
                    font.pixelSize: 14
                    elide: Text.ElideRight
                }
            }
        }

        ColumnLayout {  // Akasha.cv rank
            Layout.fillWidth: true
            Layout.topMargin: 2
            spacing: 1
            visible: !!(bc.c && bc.c.akasha)
            Text {
                Layout.fillWidth: true
                text: bc.c && bc.c.akasha ? "Akasha  " + bc.c.akasha.rank : ""
                color: bc.tint
                font.pixelSize: 13
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                text: bc.c && bc.c.akasha ? bc.c.akasha.calc : ""
                color: "#8A94A9"
                font.pixelSize: 11
                elide: Text.ElideRight
            }
        }
    }

    // ── right: the five artifacts ────────────────────────────────────────
    Column {
        x: 812; y: 34
        width: 356
        spacing: 8
        Repeater {
            model: bc.c ? bc.c.artifacts : []
            delegate: Panel {
                id: tile
                required property var modelData
                width: 356; height: 108

                Art {
                    x: 12; y: 12
                    width: 64; height: 64
                    source: tile.modelData.iconUrl
                    rarity: tile.modelData.rarity
                    fallback: tile.modelData.slot.charAt(0).toUpperCase()
                }
                Text {
                    x: 12; y: 82
                    width: 64
                    horizontalAlignment: Text.AlignHCenter
                    text: "+" + tile.modelData.level
                    color: "#B9C2D3"
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                }
                Column {            // main stat, the artifact's score, who wears it
                    x: 90; y: 12
                    width: 98
                    spacing: 1
                    Text {
                        width: parent.width
                        text: tile.modelData.main.label.replace(" DMG Bonus", " DMG")
                        color: "#A9B3C6"
                        font.pixelSize: 11
                        elide: Text.ElideRight
                    }
                    Text {
                        width: parent.width
                        text: tile.modelData.main.text
                        color: "#FFFFFF"
                        font.pixelSize: 22
                        font.weight: Font.Bold
                        elide: Text.ElideRight
                    }
                    Rectangle {
                        width: scoreText.implicitWidth + 14
                        height: 20
                        radius: 10
                        color: Qt.rgba(bc.tint.r, bc.tint.g, bc.tint.b, 0.2)
                        Text {
                            id: scoreText
                            anchors.centerIn: parent
                            text: bc.rv ? "RV " + tile.modelData.rollText : "CV " + tile.modelData.cvText
                            color: bc.tint
                            font.pixelSize: 12
                            font.weight: Font.Bold
                        }
                    }
                    Text {
                        width: parent.width
                        visible: (tile.modelData.owner || "") !== ""
                        text: "from " + (tile.modelData.owner || "")
                        color: "#8A94A9"
                        font.pixelSize: 10
                        elide: Text.ElideRight
                    }
                }
                Column {            // substats: value, then one dot per roll or its roll value
                    x: 194; y: 12
                    spacing: 5
                    Repeater {
                        model: tile.modelData.subs
                        delegate: Item {
                            id: sub
                            required property var modelData
                            readonly property bool hot: bc.rv ? modelData.counted
                                                              : (modelData.key === "critRate_" || modelData.key === "critDMG_")
                            width: 152; height: 20
                            Text {
                                anchors.left: parent.left
                                anchors.verticalCenter: parent.verticalCenter
                                width: 68
                                text: sub.modelData.label.replace("Elemental Mastery", "EM").replace("Energy Recharge", "ER")
                                color: sub.hot ? "#FFFFFF" : "#8E98AC"
                                font.pixelSize: 12
                                elide: Text.ElideRight
                            }
                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 66
                                anchors.verticalCenter: parent.verticalCenter
                                width: 40
                                horizontalAlignment: Text.AlignRight
                                text: sub.modelData.text
                                color: sub.hot ? "#FFFFFF" : "#A9B3C6"
                                font.pixelSize: 12
                                font.weight: Font.DemiBold
                            }
                            Text {
                                visible: bc.rv
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                text: sub.modelData.rvText
                                color: sub.hot ? bc.tint : "#6F7A90"
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                            }
                            RollDots {
                                visible: !bc.rv
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                layoutDirection: Qt.RightToLeft
                                rolls: sub.modelData.rolls
                                tint: sub.hot ? bc.tint : "#6F7A90"
                            }
                        }
                    }
                }
            }
        }
    }

    Panel {         // a character without artifacts
        x: 812; y: 34
        width: 356; height: 108
        visible: !!(bc.c && bc.c.artifacts.length === 0)
        Column {
            anchors.centerIn: parent
            spacing: 4
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "No artifacts equipped"
                color: "#A9B3C6"
                font.pixelSize: 15
                font.weight: Font.DemiBold
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Stats are the character's base plus weapon"
                color: "#6F7A90"
                font.pixelSize: 11
            }
        }
    }

    Text {   // whose build this is
        anchors.right: parent.right
        anchors.rightMargin: 32
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 11
        text: bc.footer
        visible: bc.footer !== ""
        color: "#566179"
        font.pixelSize: 10
    }

    Rectangle {     // the frame, over everything
        anchors.fill: parent
        color: "transparent"
        border.width: 1
        border.color: Qt.rgba(bc.tint.r, bc.tint.g, bc.tint.b, 0.45)
    }
}
