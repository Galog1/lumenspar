import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Lumenspar

// "Team & damage" tab of the Optimizer: build a team of up to four characters,
// set the enemy, toggle every conditional buff, and read each member's damage
// table and the team's rotation DPS. All data and actions come from the `team`
// backend; every access is guarded so the panel loads with empty data.
ColumnLayout {
    id: panel
    spacing: 18

    readonly property var members: team.members || []
    readonly property var conditions: team.conditions || []
    readonly property var formulas: team.formulas || []
    readonly property var stats: team.stats || []
    readonly property var enemy: team.enemy || ({})
    readonly property var rotation: team.rotation || ({})
    readonly property var rotMembers: rotation.members || []
    readonly property int selectedSlot: team.selected || 0
    readonly property var selectedMember: members[selectedSlot] || ({})
    property string col: "avg"   // damage column shown: "avg" | "crit" | "nonCrit"

    function fmt(v) {
        if (v === null || v === undefined) return "…"
        return Number(v).toLocaleString(Qt.locale(), "f", 0)
    }

    function colValue(f) {
        return col === "crit" ? f.crit : (col === "nonCrit" ? f.nonCrit : f.avg)
    }

    // amp/cata: undefined keeps the current value
    function applyEnemy(level, res, amp, cata) {
        team.setEnemy(level, res, amp, cata)
    }

    component Field: TextField {
        id: field
        implicitHeight: 32
        color: Theme.text
        font.pixelSize: 13
        placeholderTextColor: Theme.textDim
        selectByMouse: true
        background: Rectangle {
            radius: 8; color: Theme.bgAlt
            border.color: field.activeFocus ? Theme.accent : Theme.border
            border.width: 1
        }
    }

    component NumBox: SpinBox {
        id: nb
        implicitWidth: 110
        implicitHeight: 32
        editable: false
        background: Rectangle {
            radius: 8; color: Theme.bgAlt
            border.color: Theme.border
            border.width: 1
        }
        contentItem: Text {
            text: nb.value
            color: Theme.text
            font.pixelSize: 13
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        up.indicator: Text {
            x: parent.width - width - 10
            anchors.verticalCenter: parent.verticalCenter
            text: "+"; color: Theme.text; font.pixelSize: 14
        }
        down.indicator: Text {
            x: 10
            anchors.verticalCenter: parent.verticalCenter
            text: "−"; color: Theme.text; font.pixelSize: 14
        }
    }

    // portrait circle with a rarity gradient; falls back to the initial
    component Portrait: Rectangle {
        id: portrait
        property string iconUrl: ""
        property string name: ""
        property int rarity: 5
        radius: width / 2
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.darker(Theme.rarity(portrait.rarity), 2.6) }
            GradientStop { position: 1.0; color: Qt.darker(Theme.rarity(portrait.rarity), 1.5) }
        }
        Image {
            anchors.fill: parent
            anchors.margins: 3
            source: portrait.iconUrl
            visible: status === Image.Ready
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            smooth: true
            mipmap: true
        }
        Text {
            anchors.centerIn: parent
            visible: portrait.iconUrl === ""
            text: portrait.name.charAt(0)
            color: "#FFFFFF"
            opacity: 0.7
            font.pixelSize: portrait.width * 0.3
            font.weight: Font.DemiBold
        }
    }

    // ── pick-a-character popup shared by the four slots ───────────────
    Popup {
        id: pickPopup
        property int slot: 0
        parent: Overlay.overlay
        anchors.centerIn: parent
        modal: true
        padding: 16
        width: Math.min(640, (parent ? parent.width : 640) - 40)
        height: Math.min(420, implicitHeight)
        background: Rectangle {
            radius: 14
            color: Theme.surface
            border.width: 1
            border.color: Theme.border
        }
        contentItem: ColumnLayout {
            spacing: 12
            Text {
                text: "Choose a character"
                color: Theme.text
                font.pixelSize: 15
                font.weight: Font.DemiBold
            }
            Flickable {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredHeight: Math.min(contentHeight, 280)
                contentWidth: width
                contentHeight: pickFlow.height
                clip: true
                Flow {
                    id: pickFlow
                    width: parent.width
                    spacing: 8
                    Repeater {
                        model: team.candidates || []
                        delegate: Rectangle {
                            id: cand
                            required property var modelData
                            readonly property color tint: Theme.element(modelData.element)
                            width: 150; height: 60
                            radius: 12
                            color: Theme.bgAlt
                            border.width: 1
                            border.color: Theme.border
                            HoverHandler { id: candHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler {
                                onTapped: {
                                    team.setMember(pickPopup.slot, cand.modelData.key)
                                    pickPopup.close()
                                }
                            }
                            Rectangle {
                                anchors.fill: parent
                                radius: 12
                                color: "transparent"
                                border.width: candHover.hovered ? 1 : 0
                                border.color: cand.tint
                            }
                            Row {
                                anchors.fill: parent
                                anchors.leftMargin: 6
                                spacing: 8
                                Portrait {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 48; height: 48
                                    iconUrl: cand.modelData.iconUrl || ""
                                    name: cand.modelData.name || ""
                                }
                                Column {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width - 48 - 14
                                    Text {
                                        width: parent.width
                                        text: cand.modelData.name || ""
                                        color: Theme.text
                                        font.pixelSize: 12
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        width: parent.width
                                        text: cand.modelData.source || ""
                                        color: Theme.textDim
                                        font.pixelSize: 10
                                    }
                                }
                            }
                        }
                    }
                }
            }
            GhostButton {
                label: "Remove from team"
                implicitHeight: 32
                onClicked: {
                    team.setMember(pickPopup.slot, "")
                    pickPopup.close()
                }
            }
        }
    }

    // ── team ──────────────────────────────────────────────────────────
    Card {
        title: "Team"
        subtitle: "Up to four characters. Showcase builds are used as they are; other characters come from your inventory scan with what they have equipped. Click a member to see their damage."

        Row {
            spacing: 14
            Repeater {
                model: 4
                delegate: Column {
                    id: slotCol
                    required property int index
                    readonly property var m: panel.members[index] || ({})
                    readonly property bool filled: !!m.key
                    readonly property bool current: filled && panel.selectedSlot === index
                    readonly property color tint: Theme.element(m.element)
                    spacing: 8

                    Rectangle {
                        width: 110; height: 132
                        radius: 14
                        color: slotCol.current ? Qt.rgba(slotCol.tint.r, slotCol.tint.g, slotCol.tint.b, 0.18)
                                               : (slotCol.filled ? Theme.surface : Theme.bgAlt)
                        border.width: slotCol.current ? 2 : 1
                        border.color: slotCol.current ? slotCol.tint : Theme.border

                        HoverHandler { cursorShape: slotCol.filled ? Qt.PointingHandCursor : Qt.ArrowCursor }
                        TapHandler {
                            enabled: slotCol.filled
                            onTapped: team.select(slotCol.index)
                        }

                        Portrait {
                            visible: slotCol.filled
                            anchors.horizontalCenter: parent.horizontalCenter
                            y: 12
                            width: 64; height: 64
                            iconUrl: slotCol.m.iconUrl || ""
                            name: slotCol.m.name || ""
                        }
                        Text {
                            visible: slotCol.filled
                            anchors.horizontalCenter: parent.horizontalCenter
                            y: 84
                            width: parent.width - 10
                            horizontalAlignment: Text.AlignHCenter
                            text: slotCol.m.name || ""
                            color: Theme.text
                            font.pixelSize: 12
                            elide: Text.ElideRight
                        }
                        Text {
                            visible: slotCol.filled
                            anchors.horizontalCenter: parent.horizontalCenter
                            y: 104
                            text: slotCol.m.source || ""
                            color: Theme.textDim
                            font.pixelSize: 10
                        }
                        Text {
                            visible: !slotCol.filled
                            anchors.centerIn: parent
                            text: "+"
                            color: Theme.textDim
                            font.pixelSize: 32
                        }
                    }
                    GhostButton {
                        width: 110
                        implicitHeight: 30
                        label: slotCol.filled ? "Change" : "Add"
                        onClicked: {
                            pickPopup.slot = slotCol.index
                            pickPopup.open()
                        }
                    }
                }
            }
        }
    }

    Text {
        Layout.fillWidth: true
        visible: !!team.status
        text: team.status || ""
        color: Theme.textDim
        font.pixelSize: 12
        wrapMode: Text.WordWrap
    }

    // ── enemy ─────────────────────────────────────────────────────────
    Card {
        title: "Enemy"

        Flow {
            Layout.fillWidth: true
            spacing: 10
            Text {
                height: 32
                verticalAlignment: Text.AlignVCenter
                text: "Level"
                color: Theme.textDim
                font.pixelSize: 13
            }
            NumBox {
                from: 1; to: 120
                value: panel.enemy.level || 90
                onValueModified: panel.applyEnemy(value, Number(panel.enemy.res || 0),
                                                  panel.enemy.amp || "", panel.enemy.cata || "")
            }
            Text {
                height: 32
                verticalAlignment: Text.AlignVCenter
                text: "Resistance %"
                color: Theme.textDim
                font.pixelSize: 13
            }
            Field {
                width: 70
                text: String(panel.enemy.res ?? 10)
                validator: DoubleValidator { locale: "C" }
                onEditingFinished: {
                    const v = Number(text)
                    panel.applyEnemy(panel.enemy.level || 90, isNaN(v) ? 0 : v,
                                     panel.enemy.amp || "", panel.enemy.cata || "")
                }
            }
            Text {
                height: 32
                verticalAlignment: Text.AlignVCenter
                text: "Reaction"
                color: Theme.textDim
                font.pixelSize: 13
            }
            Repeater {
                model: [{ label: "None", amp: "", cata: "" },
                        { label: "Vaporize", amp: "vaporize", cata: "" },
                        { label: "Melt", amp: "melt", cata: "" },
                        { label: "Aggravate", amp: "", cata: "aggravate" },
                        { label: "Spread", amp: "", cata: "spread" }]
                delegate: Pill {
                    required property var modelData
                    label: modelData.label
                    checked: (panel.enemy.amp || "") === modelData.amp
                             && (panel.enemy.cata || "") === modelData.cata
                    onClicked: panel.applyEnemy(panel.enemy.level || 90, Number(panel.enemy.res || 0),
                                                modelData.amp, modelData.cata)
                }
            }
        }
    }

    // ── conditions ────────────────────────────────────────────────────
    Card {
        title: "Conditions"
        subtitle: "Every conditional buff the team can have: talents, passives and constellations, weapon passives, artifact sets, elemental resonance and enemy states. Hover a condition for the game's description."

        Text {
            Layout.fillWidth: true
            visible: panel.conditions.length === 0
            text: "Add characters to see their conditions."
            color: Theme.textDim
            font.pixelSize: 13
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 6
            Repeater {
                model: panel.conditions
                delegate: ColumnLayout {
                    id: cond
                    required property var modelData
                    required property int index
                    readonly property var prev: index > 0 ? (panel.conditions[index - 1] || ({})) : ({})
                    readonly property bool newMember: index === 0 || (modelData.member || "") !== (prev.member || "")
                    readonly property bool newSheet: newMember || (modelData.sheetTitle || "") !== (prev.sheetTitle || "")
                    Layout.fillWidth: true
                    spacing: 4

                    Text {
                        Layout.fillWidth: true
                        visible: cond.newMember && !!cond.modelData.member
                        topPadding: 8
                        text: cond.modelData.member || ""
                        color: Theme.text
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: cond.newSheet && !!cond.modelData.sheetTitle
                        text: cond.modelData.sheetTitle || ""
                        color: Theme.accent
                        font.pixelSize: 12
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        Text {
                            id: condLabel
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignVCenter
                            text: cond.modelData.label || cond.modelData.name || ""
                            color: Theme.text
                            font.pixelSize: 13
                            wrapMode: Text.WordWrap
                            HoverHandler { id: condHover }
                            ToolTip.visible: condHover.hovered && !!cond.modelData.detail
                            ToolTip.delay: 400
                            ToolTip.timeout: 20000
                            ToolTip.text: cond.modelData.detail || ""
                        }
                        Loader {
                            Layout.alignment: Qt.AlignVCenter | Qt.AlignRight
                            sourceComponent: cond.modelData.type === "num" ? numCtl
                                           : (cond.modelData.type === "list" ? listCtl : boolCtl)
                        }
                        Component {
                            id: boolCtl
                            Pill {
                                label: cond.modelData.value ? "✅ On" : "❌ Off"
                                checked: !!cond.modelData.value
                                onClicked: team.setConditional(cond.modelData.id, !cond.modelData.value)
                            }
                        }
                        Component {
                            id: numCtl
                            NumBox {
                                from: cond.modelData.min || 0
                                to: cond.modelData.max || 10
                                value: cond.modelData.value || 0
                                onValueModified: team.setConditional(cond.modelData.id, value)
                            }
                        }
                        Component {
                            id: listCtl
                            Row {
                                spacing: 6
                                Pill {
                                    label: "Off"
                                    checked: cond.modelData.value === null || cond.modelData.value === undefined
                                             || cond.modelData.value === ""
                                    onClicked: team.setConditional(cond.modelData.id, "")
                                }
                                Repeater {
                                    model: cond.modelData.options || []
                                    delegate: Pill {
                                        required property var modelData
                                        label: modelData.label
                                        checked: cond.modelData.value === modelData.value
                                        onClicked: team.setConditional(cond.modelData.id, modelData.value)
                                    }
                                }
                            }
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 1
                        color: Qt.rgba(1, 1, 1, 0.05)
                    }
                }
            }
        }
    }

    // ── damage ────────────────────────────────────────────────────────
    Card {
        title: "Damage — " + (panel.selectedMember.name || "")

        Flow {
            Layout.fillWidth: true
            spacing: 10
            Repeater {
                model: panel.stats
                delegate: Rectangle {
                    id: statChip
                    required property var modelData
                    implicitWidth: Math.max(lbl.implicitWidth, val.implicitWidth) + 20
                    implicitHeight: 44
                    radius: 10
                    color: Theme.bgAlt
                    border.width: 1
                    border.color: Theme.border
                    Column {
                        anchors.centerIn: parent
                        Text {
                            id: lbl
                            text: statChip.modelData.label || ""
                            color: Theme.textDim
                            font.pixelSize: 11
                        }
                        Text {
                            id: val
                            text: statChip.modelData.text || ""
                            color: Theme.text
                            font.pixelSize: 14
                            font.weight: Font.DemiBold
                        }
                    }
                }
            }
        }

        Row {
            spacing: 8
            Repeater {
                model: [{ key: "avg", label: "Average" }, { key: "crit", label: "Crit" },
                        { key: "nonCrit", label: "Non-crit" }]
                delegate: Pill {
                    required property var modelData
                    label: modelData.label
                    checked: panel.col === modelData.key
                    onClicked: panel.col = modelData.key
                }
            }
        }

        Text {
            Layout.fillWidth: true
            visible: panel.formulas.length === 0
            text: team.busy ? "Calculating…" : "Pick a team member."
            color: Theme.textDim
            font.pixelSize: 13
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0
            Repeater {
                model: panel.formulas
                delegate: ColumnLayout {
                    id: frow
                    required property var modelData
                    required property int index
                    readonly property var prev: index > 0 ? (panel.formulas[index - 1] || ({})) : ({})
                    readonly property bool newGroup: index === 0 || (modelData.group || "") !== (prev.group || "")
                    Layout.fillWidth: true
                    spacing: 0

                    Text {
                        Layout.fillWidth: true
                        visible: frow.newGroup && !!frow.modelData.group
                        topPadding: 6
                        bottomPadding: 2
                        text: frow.modelData.group || ""
                        color: Theme.accent
                        font.pixelSize: 12
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: 3
                        Layout.bottomMargin: 3
                        spacing: 10
                        Text {
                            Layout.fillWidth: true
                            text: frow.modelData.label || ""
                            color: Theme.text
                            font.pixelSize: 13
                            wrapMode: Text.WordWrap
                        }
                        Text {
                            text: panel.fmt(panel.colValue(frow.modelData))
                            color: Theme.text
                            font.pixelSize: 13
                            font.weight: Font.DemiBold
                        }
                        Text {
                            text: "×"
                            color: Theme.textDim
                            font.pixelSize: 13
                        }
                        NumBox {
                            implicitWidth: 90
                            from: 0; to: 99
                            value: frow.modelData.count || 0
                            onValueModified: team.setCount(frow.modelData.key, value)
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 1
                        color: Qt.rgba(1, 1, 1, 0.05)
                    }
                }
            }
        }
    }

    // ── rotation ──────────────────────────────────────────────────────
    Card {
        title: "Rotation & DPS"
        subtitle: "Set how many times each hit lands in one rotation on each member's damage table, and the rotation length."

        Flow {
            Layout.fillWidth: true
            spacing: 10
            Text {
                height: 32
                verticalAlignment: Text.AlignVCenter
                text: "Rotation length (s)"
                color: Theme.textDim
                font.pixelSize: 13
            }
            Field {
                width: 80
                text: String(panel.rotation.seconds ?? 20)
                validator: DoubleValidator { bottom: 0; locale: "C" }
                onEditingFinished: {
                    const v = Number(text)
                    if (!isNaN(v)) team.setSeconds(v)
                }
            }
            AccentButton {
                label: "Calculate team DPS"
                implicitHeight: 34
                enabledState: !team.busy
                onClicked: team.computeTeam()
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4
            Repeater {
                model: panel.rotMembers
                delegate: Text {
                    required property var modelData
                    Layout.fillWidth: true
                    text: (modelData.name || "") + ": " + panel.fmt(modelData.total) + " damage · "
                          + panel.fmt(modelData.dps) + " DPS"
                    color: Theme.text
                    font.pixelSize: 13
                    wrapMode: Text.WordWrap
                }
            }
            Text {
                Layout.fillWidth: true
                visible: panel.rotMembers.length > 0
                text: "Team: " + panel.fmt(panel.rotation.teamTotal) + " damage · "
                      + panel.fmt(panel.rotation.teamDps) + " DPS"
                color: Theme.text
                font.pixelSize: 14
                font.weight: Font.Bold
                wrapMode: Text.WordWrap
            }
            Text {
                Layout.fillWidth: true
                visible: !!panel.rotation.stale && panel.rotMembers.length > 0
                text: "Out of date — recalculate"
                color: Theme.textDim
                font.pixelSize: 12
            }
        }
    }
}
