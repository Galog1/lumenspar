import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Lumenspar

// "Team & damage" tab of the Optimizer: build a team of up to four characters,
// toggle every conditional buff and read each member's damage table. Nothing
// is typed in: every setting is a pill or a choice. All data and actions come from the `team`
// backend; every access is guarded so the panel loads with empty data.
ColumnLayout {
    id: panel
    spacing: 18

    readonly property var members: team.members || []
    readonly property var conditions: team.conditions || []
    readonly property var formulas: team.formulas || []
    readonly property var stats: team.stats || []
    readonly property int selectedSlot: team.selected || 0
    readonly property var selectedMember: members[selectedSlot] || ({})
    property string col: "avg"   // damage column shown: "avg" | "crit" | "nonCrit"

    function fmt(v) {
        if (v === null || v === undefined) return "…"
        return Number(v).toLocaleString(Qt.locale(), "f", 0)
    }

    // the conditions grouped by member and sheet, in display order
    function groupConditions(list) {
        const out = []
        for (const c of list) {
            const last = out.length > 0 ? out[out.length - 1] : null
            if (last && last.member === (c.member || "") && last.sheetTitle === (c.sheetTitle || ""))
                last.rows.push(c)
            else
                out.push({ member: c.member || "", sheetTitle: c.sheetTitle || "",
                           newMember: !last || last.member !== (c.member || ""), rows: [c] })
        }
        return out
    }

    function filterByName(list, query) {
        const q = (query || "").trim().toLowerCase()
        if (!q) return list || []
        return (list || []).filter(c => (c.name || "").toLowerCase().indexOf(q) >= 0)
    }

    function weaponIndex(choices, key) {
        for (let i = 0; i < (choices || []).length; i++)
            if (choices[i].key === key) return i
        return -1
    }

    function colValue(f) {
        return col === "crit" ? f.crit : (col === "nonCrit" ? f.nonCrit : f.avg)
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

    component Combo: ComboBox {
        id: cb
        implicitHeight: 32
        implicitWidth: 220
        font.pixelSize: 13
        textRole: "name"
        background: Rectangle {
            radius: 8; color: Theme.bgAlt
            border.color: cb.activeFocus ? Theme.accent : Theme.border
            border.width: 1
        }
        contentItem: Text {
            leftPadding: 10
            rightPadding: 26
            text: cb.displayText
            color: Theme.text
            font.pixelSize: 13
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        indicator: Text {
            x: cb.width - width - 10
            anchors.verticalCenter: parent.verticalCenter
            text: "▾"
            color: Theme.textDim
            font.pixelSize: 12
        }
        delegate: ItemDelegate {
            id: dlg
            required property var modelData
            required property int index
            width: cb.width
            highlighted: cb.highlightedIndex === index
            background: Rectangle { color: dlg.highlighted ? Theme.surfaceHi : Theme.bgAlt }
            contentItem: Text {
                text: dlg.modelData.name
                color: Theme.text
                font.pixelSize: 13
                elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
            }
        }
        popup: Popup {
            y: cb.height + 2
            width: cb.width
            implicitHeight: Math.min(contentItem.implicitHeight + 2, 320)
            padding: 1
            contentItem: ListView {
                clip: true
                implicitHeight: contentHeight
                model: cb.popup.visible ? cb.delegateModel : null
                currentIndex: cb.highlightedIndex
            }
            background: Rectangle {
                radius: 8; color: Theme.bgAlt
                border.color: Theme.border
                border.width: 1
            }
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
        property string tab: "mine"
        parent: Overlay.overlay
        anchors.centerIn: parent
        modal: true
        padding: 16
        width: Math.min(640, (parent ? parent.width : 640) - 40)
        height: Math.min(460, (parent ? parent.height : 460) - 40)
        onAboutToShow: {
            pickSearch.text = ""
            if (tab === "all") team.ensurePortraits()
        }
        background: Rectangle {
            radius: 14
            color: Theme.surface
            border.width: 1
            border.color: Theme.border
        }
        contentItem: ColumnLayout {
            spacing: 12
            Row {
                spacing: 8
                Pill {
                    label: "My characters"
                    checked: pickPopup.tab === "mine"
                    onClicked: pickPopup.tab = "mine"
                }
                Pill {
                    label: "All characters"
                    checked: pickPopup.tab === "all"
                    onClicked: {
                        pickPopup.tab = "all"
                        team.ensurePortraits()
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                Field {
                    id: pickSearch
                    Layout.fillWidth: true
                    placeholderText: "Search characters"
                }
                GhostButton {
                    label: "Remove from team"
                    implicitHeight: 32
                    onClicked: {
                        team.setMember(pickPopup.slot, "", "owned")
                        pickPopup.close()
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                visible: pickPopup.tab === "mine" && (team.owned || []).length === 0
                text: "No builds yet — fetch your showcase in Build Cards or scan your inventory."
                color: Theme.textDim
                font.pixelSize: 13
                wrapMode: Text.WordWrap
            }
            Text {
                Layout.fillWidth: true
                visible: pickFlow.model.length === 0 && ((team.owned || []).length > 0 || pickPopup.tab === "all")
                text: "No characters match."
                color: Theme.textDim
                font.pixelSize: 13
            }
            Flickable {
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: width
                contentHeight: pickFlow.height
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}
                Flow {
                    id: pickFlow
                    width: parent.width - 10
                    spacing: 8
                    property var model: panel.filterByName(
                        pickPopup.tab === "mine" ? team.owned : team.allCharacters, pickSearch.text)
                    Repeater {
                        model: pickFlow.model
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
                                    team.setMember(pickPopup.slot, cand.modelData.key,
                                                   pickPopup.tab === "mine" ? "owned" : "game")
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
                                    rarity: cand.modelData.rarity || 5
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
                                        visible: pickPopup.tab === "mine"
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
        }
    }

    // ── team ──────────────────────────────────────────────────────────
    Card {
        title: "Team"
        subtitle: "Up to four characters. Showcase builds are used as they are; other characters come from your inventory scan with what they have equipped, or from the full list with settings you choose. Click a member to see their damage."

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

        Text {
            Layout.fillWidth: true
            visible: panel.selectedMember.source === "game"
            text: "Settings for " + (panel.selectedMember.name || "")
            color: Theme.text
            font.pixelSize: 14
            font.weight: Font.DemiBold
        }
        Flow {
            id: gameSettings
            Layout.fillWidth: true
            visible: panel.selectedMember.source === "game"
            spacing: 16
            readonly property var st: panel.selectedMember.settings || ({})

            Column {
                spacing: 4
                Text { text: "Constellation"; color: Theme.textDim; font.pixelSize: 12 }
                Row {
                    spacing: 6
                    Repeater {
                        model: 7
                        delegate: Pill {
                            required property int index
                            label: "C" + index
                            checked: (gameSettings.st.constellation || 0) === index
                            onClicked: team.setSetting(panel.selectedSlot, "constellation", index)
                        }
                    }
                }
            }
            Column {
                spacing: 4
                Text { text: "Weapon"; color: Theme.textDim; font.pixelSize: 12 }
                Combo {
                    model: team.weaponChoices || []
                    currentIndex: panel.weaponIndex(team.weaponChoices, gameSettings.st.weapon)
                    onActivated: (i) => team.setSetting(panel.selectedSlot, "weapon", team.weaponChoices[i].key)
                }
            }
            Column {
                spacing: 4
                Text { text: "Refinement"; color: Theme.textDim; font.pixelSize: 12 }
                Row {
                    spacing: 6
                    Repeater {
                        model: 5
                        delegate: Pill {
                            required property int index
                            label: "R" + (index + 1)
                            checked: (gameSettings.st.refinement || 1) === index + 1
                            onClicked: team.setSetting(panel.selectedSlot, "refinement", index + 1)
                        }
                    }
                }
            }
        }
        Text {
            Layout.fillWidth: true
            visible: panel.selectedMember.source === "game"
            text: "Level 90, talents 9/9/9 and weapon level 90. Characters from the full list have no artifacts here; their talents, passives, constellations and weapon still apply."
            color: Theme.textDim
            font.pixelSize: 12
            wrapMode: Text.WordWrap
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
                model: panel.groupConditions(panel.conditions)
                delegate: ColumnLayout {
                    id: grp
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 6

                    Text {
                        Layout.fillWidth: true
                        visible: grp.modelData.newMember && !!grp.modelData.member
                        topPadding: 8
                        text: grp.modelData.member
                        color: Theme.text
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: !!grp.modelData.sheetTitle
                        text: grp.modelData.sheetTitle
                        color: Theme.accent
                        font.pixelSize: 12
                    }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 8
                        Repeater {
                            model: grp.modelData.rows
                            delegate: Rectangle {
                                id: tile
                                required property var modelData
                                readonly property string kind: modelData.type === "num" ? "num"
                                    : (modelData.type === "list" ? "list" : "bool")
                                readonly property var val: modelData.value
                                readonly property bool unset: val === null || val === undefined || val === ""
                                readonly property bool active: kind === "bool" ? !!val
                                    : (kind === "num" ? Number(val || 0) > 0 : !unset)

                                implicitWidth: tileBody.implicitWidth + 24
                                width: Math.min(260, implicitWidth)
                                height: Math.max(44, tileBody.implicitHeight + 16)
                                radius: 10
                                color: Theme.bgAlt
                                border.width: 1
                                border.color: active ? Theme.accent : Theme.border

                                HoverHandler {
                                    id: tileHover
                                    cursorShape: tile.kind === "bool" ? Qt.PointingHandCursor : Qt.ArrowCursor
                                }
                                TapHandler {
                                    enabled: tile.kind === "bool"
                                    onTapped: team.setConditional(tile.modelData.id, !tile.val)
                                }
                                ToolTip.visible: tileHover.hovered && !!tile.modelData.detail
                                ToolTip.delay: 400
                                ToolTip.timeout: 20000
                                ToolTip.text: tile.modelData.detail || ""

                                ColumnLayout {
                                    id: tileBody
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.verticalCenter: parent.verticalCenter
                                    anchors.leftMargin: 12
                                    anchors.rightMargin: 12
                                    spacing: 6

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        Rectangle {
                                            visible: tile.kind === "bool"
                                            Layout.preferredWidth: 16
                                            Layout.preferredHeight: 16
                                            Layout.alignment: Qt.AlignVCenter
                                            radius: 4
                                            color: tile.active ? Theme.accent : "transparent"
                                            border.width: 1
                                            border.color: tile.active ? Theme.accent : Theme.border
                                            Text {
                                                anchors.centerIn: parent
                                                visible: tile.active
                                                text: "✓"
                                                color: "#FFFFFF"
                                                font.pixelSize: 11
                                                font.weight: Font.Bold
                                            }
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            Layout.alignment: Qt.AlignVCenter
                                            text: tile.modelData.label || tile.modelData.name || ""
                                            color: Theme.text
                                            font.pixelSize: 12
                                            wrapMode: Text.WordWrap
                                            maximumLineCount: 2
                                            elide: Text.ElideRight
                                        }
                                    }
                                    Flow {
                                        visible: tile.kind === "list" || tile.kind === "num"
                                        Layout.fillWidth: true
                                        spacing: 4
                                        Repeater {
                                            model: tile.kind === "num" ? (tile.modelData.options || [])
                                                   : [{ value: "", label: "Off" }].concat(tile.modelData.options || [])
                                            delegate: Rectangle {
                                                id: opt
                                                required property var modelData
                                                readonly property bool on: tile.kind === "num"
                                                    ? Number(tile.val || 0) === modelData.value
                                                    : (modelData.value === "" ? tile.unset : tile.val === modelData.value)
                                                implicitWidth: optText.implicitWidth + 16
                                                height: 22
                                                radius: 11
                                                color: on ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18)
                                                          : Theme.surfaceGlass
                                                border.width: 1
                                                border.color: on ? Theme.accent : Theme.border
                                                Text {
                                                    id: optText
                                                    anchors.centerIn: parent
                                                    text: opt.modelData.label
                                                    color: opt.on ? Theme.accent : Theme.text
                                                    font.pixelSize: 11
                                                }
                                                MouseArea {
                                                    anchors.fill: parent
                                                    cursorShape: Qt.PointingHandCursor
                                                    onClicked: team.setConditional(tile.modelData.id, opt.modelData.value)
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
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
            Text {
                height: 32
                verticalAlignment: Text.AlignVCenter
                text: "Reaction on " + (panel.selectedMember.name || "the selected member") + "'s hits:"
                color: Theme.textDim
                font.pixelSize: 13
            }
            Repeater {
                model: team.reactionOptions
                delegate: Pill {
                    required property var modelData
                    label: modelData.label
                    checked: team.reaction === modelData.value
                    onClicked: team.setReaction(modelData.value)
                }
            }
        }
        Text {
            Layout.fillWidth: true
            visible: (team.reactionOptions || []).length <= 1
            text: "No amplifying or catalyze reaction is possible for "
                  + (panel.selectedMember.name || "this character") + " with this team."
            color: Theme.textDim
            font.pixelSize: 12
            wrapMode: Text.WordWrap
        }
        Text {
            Layout.fillWidth: true
            text: "Transformative and Lunar reactions (Swirl, Overloaded, Bloom, Lunar-Charged, …) appear in the damage table when the team can trigger them."
            color: Theme.textDim
            font.pixelSize: 12
            wrapMode: Text.WordWrap
        }

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
}
