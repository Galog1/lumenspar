import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import Lumenspar

// Optimizer: picks the best artifacts from a scanned .GOOD file for one
// character, by damage estimate, stat weights, target values or a stat ratio,
// and shows the top builds as cards next to the current one.
Item {
    id: page
    objectName: "optimizerPage"

    // ── goal state (always reassigned, never mutated, so bindings update) ──
    property string tab: "optimize"   // "optimize" | "team"
    property string scaling: "atk"
    property string mode: "damage"
    property var priority: ["critRate_", "critDMG_", "atk_"]
    property var mains: ({ sands: ["atk_"], goblet: [], circlet: ["critRate_", "critDMG_"] })
    property var weights: ({})
    property var targets: ({})
    property var ratio: ["critRate_", 1, "critDMG_", 2]
    property var minimums: []   // [{key, value}]
    property string setKey: ""
    property real extraCrit: 0
    property bool useEquipped: true
    property int minLevel: 16
    property int shown: 0       // result on show; -1 = the current build
    property string lastSelected: ""
    property string boardId: ""
    property string boardVariant: ""
    property string teamChoice: ""   // the hit picked for Team damage; "" = the default

    readonly property var teamInfo: optimizer.teamInfo || ({})
    readonly property var teamTargets: teamInfo.targets || []
    readonly property string teamTarget: {
        for (let i = 0; i < teamTargets.length; i++)
            if (teamTargets[i].key === teamChoice) return teamChoice
        const d = teamInfo.defaultTarget || ""
        for (let i = 0; i < teamTargets.length; i++)
            if (teamTargets[i].key === d) return d
        return teamTargets.length > 0 ? teamTargets[0].key : ""
    }

    readonly property var substats: optimizer.substats || []
    readonly property var results: optimizer.results || []
    readonly property var entry: shown >= 0 ? (results[shown] || null) : null
    readonly property bool showCurrent: shown === -1 || entry === null
    readonly property var currentCard: optimizer.current && optimizer.current.card ? optimizer.current.card : null
    readonly property var shownCard: showCurrent ? currentCard : (entry ? entry.card : null)
    readonly property var crit: optimizer.crit || ({})
    readonly property var minKeys: ["enerRech_", "critRate_", "critDMG_", "eleMas", "atk", "hp", "def"]
    readonly property var minLabels: ["Energy Recharge", "CRIT Rate", "CRIT DMG", "Elemental Mastery",
                                      "ATK (total)", "HP (total)", "DEF (total)"]

    function toggle(list, key) {
        const i = list.indexOf(key)
        if (i < 0) return list.concat([key])
        return list.filter(function(k) { return k !== key })
    }

    function labelOf(key) {
        for (let i = 0; i < substats.length; i++)
            if (substats[i].key === key) return substats[i].label
        return key
    }

    function resetForScaling() {
        const pct = scaling === "eleMas" ? "eleMas" : scaling + "_"
        const elem = optimizer.element ? optimizer.element + "_dmg_" : ""
        mains = {
            sands: [pct],
            goblet: scaling === "eleMas" ? ["eleMas"] : (elem ? [elem] : [pct]),
            circlet: scaling === "eleMas" ? ["eleMas", "critRate_", "critDMG_"] : ["critRate_", "critDMG_"]
        }
        priority = ["critRate_", "critDMG_", pct]
    }

    function setMinimum(i, key, value) {
        const list = minimums.slice()
        list[i] = { key: key, value: value }
        minimums = list
    }

    function minimumOf(key) {
        for (let i = 0; i < minimums.length; i++)
            if (minimums[i].key === key) return minimums[i].value
        return 0
    }

    function setPreset(key, value) {
        const list = minimums.filter(function(m) { return m.key !== key })
        if (value > 0) list.push({ key: key, value: value })
        minimums = list
    }

    function goal() {
        const w = {}
        const t = {}
        for (let i = 0; i < priority.length; i++) {
            const k = priority[i]
            const wv = weights[k]
            w[k] = typeof wv === "number" && !isNaN(wv) ? wv : 1
            const tv = targets[k]
            if (typeof tv === "number" && tv > 0) t[k] = tv
        }
        const m = {}
        for (let i = 0; i < minimums.length; i++) {
            const v = minimums[i].value
            if (typeof v === "number" && !isNaN(v)) m[minimums[i].key] = v
        }
        return {
            scaling: scaling, mode: mode, setKey: setKey, mains: mains,
            weights: w, targets: t, ratio: ratio, minimums: m,
            extraCrit: extraCrit, useEquipped: useEquipped, minLevel: minLevel, top: 5
        }
    }

    readonly property var boards: optimizer.akashaBoards || []
    readonly property var selectedBoard: {
        for (let i = 0; i < boards.length; i++)
            if (boards[i].calcId === boardId) return boards[i]
        return null
    }

    function ensureBoard() {
        if (selectedBoard === null) {
            boardId = boards.length > 0 ? boards[0].calcId : ""
            boardVariant = boards.length > 0 ? boards[0].defaultVariant : ""
        }
    }

    function loadBoardsIfNeeded() {
        if (mode === "akasha" && boards.length === 0 && !optimizer.akashaBoardsNote
                && optimizer.card && optimizer.card.name !== undefined)
            optimizer.loadBoards()
    }

    onModeChanged: loadBoardsIfNeeded()

    // a new character resets the goal to sensible defaults for its element
    Component.onCompleted: {
        page.lastSelected = optimizer.selected
        page.resetForScaling()
    }

    Connections {
        target: optimizer
        function onAkashaBoardsChanged() { page.ensureBoard() }
    }
    Connections {
        target: optimizer
        function onAkashaTop1Changed() {
            const t = optimizer.akashaTop1
            if (t && t.targets) {
                page.priority = Array.from(t.priority)
                page.targets = Object.assign({}, t.targets)
            }
        }
    }
    Connections {
        target: optimizer
        // The backend reports every change through one signal; only a new
        // character resets the goal to that character's defaults.
        function onChanged() {
            if (optimizer.selected === page.lastSelected) return
            page.lastSelected = optimizer.selected
            page.shown = 0
            page.resetForScaling()
            page.loadBoardsIfNeeded()
        }
    }

    FileDialog {
        id: fileDlg
        nameFilters: ["GOOD files (*.json)"]
        onAccepted: optimizer.chooseFile(selectedFile.toString())
    }

    component RowLabel: Text {
        Layout.preferredWidth: 130
        Layout.alignment: Qt.AlignTop
        topPadding: 6
        color: Theme.textDim
        font.pixelSize: 13
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
        font.pixelSize: 13
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
                text: dlg.modelData
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

    ScrollView {
        id: scroll
        anchors.fill: parent
        anchors.margins: 20
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            width: scroll.availableWidth
            spacing: 18

            Row {
                spacing: 8
                Pill {
                    label: "Optimize"
                    checked: page.tab === "optimize"
                    onClicked: page.tab = "optimize"
                }
                Pill {
                    label: "Team & damage"
                    checked: page.tab === "team"
                    onClicked: page.tab = "team"
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 18
                visible: page.tab === "optimize"

                // ── character ─────────────────────────────────────────────
                Card {
                    title: "Character"
                    subtitle: "Characters from your build cards. Their stats without artifacts come from the showcase; refetch a character there if it shows as needing it."

                    Text {
                        Layout.fillWidth: true
                        visible: (optimizer.characters || []).length === 0
                        text: "No build cards yet — fetch your showcase in Build Cards first."
                        color: Theme.textDim
                        font.pixelSize: 13
                    }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 10
                        visible: (optimizer.characters || []).length > 0
                        Repeater {
                            model: optimizer.characters || []
                            delegate: Rectangle {
                                id: chip
                                required property var modelData
                                readonly property bool current: modelData.avatarId === optimizer.selected
                                readonly property color tint: Theme.element(modelData.element)
                                width: 78; height: 96
                                radius: 14
                                color: current ? Qt.rgba(tint.r, tint.g, tint.b, 0.18) : Theme.surface
                                border.width: current ? 2 : 1
                                border.color: current ? tint : Theme.border
                                opacity: modelData.ready ? 1.0 : 0.45

                                HoverHandler { id: chipHover; cursorShape: Qt.PointingHandCursor }
                                TapHandler { onTapped: optimizer.setCharacter(chip.modelData.avatarId) }
                                ToolTip.visible: chipHover.hovered && !chip.modelData.ready
                                ToolTip.delay: 400
                                ToolTip.text: "Fetch the showcase again in Build Cards to optimize"

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

                // ── goal ──────────────────────────────────────────────────
                Card {
                    title: "Goal"

                    // 1. scaling stat
                    RowLayout {
                        Layout.fillWidth: true
                        visible: page.mode !== "akasha" && page.mode !== "teamdmg"
                        spacing: 10
                        RowLabel { text: "Scaling stat" }
                        Flow {
                            Layout.fillWidth: true
                            spacing: 8
                            Repeater {
                                model: [{ key: "atk", label: "ATK" }, { key: "hp", label: "HP" },
                                        { key: "def", label: "DEF" }, { key: "eleMas", label: "Elemental Mastery" }]
                                delegate: Pill {
                                    required property var modelData
                                    label: modelData.label
                                    checked: page.scaling === modelData.key
                                    onClicked: { page.scaling = modelData.key; page.resetForScaling() }
                                }
                            }
                        }
                    }

                    // 2. optimize for
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        RowLabel { text: "Optimize for" }
                        Flow {
                            Layout.fillWidth: true
                            spacing: 8
                            Repeater {
                                model: [{ key: "damage", label: "Damage estimate" }, { key: "weights", label: "Stat weights" },
                                        { key: "targets", label: "Target values" }, { key: "ratio", label: "Ratio" },
                                        { key: "akasha", label: "Akasha ranking" },
                                        { key: "teamdmg", label: "Team damage" }]
                                delegate: Pill {
                                    required property var modelData
                                    label: modelData.label
                                    checked: page.mode === modelData.key
                                    onClicked: page.mode = modelData.key
                                }
                            }
                        }
                    }

                    // 3. priority stats
                    RowLayout {
                        Layout.fillWidth: true
                        visible: page.mode !== "akasha" && page.mode !== "teamdmg"
                        spacing: 10
                        RowLabel { text: "Priority stats" }
                        Flow {
                            Layout.fillWidth: true
                            spacing: 8
                            Repeater {
                                model: page.substats
                                delegate: Pill {
                                    required property var modelData
                                    label: modelData.label
                                    checked: page.priority.indexOf(modelData.key) >= 0
                                    onClicked: page.priority = page.toggle(page.priority, modelData.key)
                                }
                            }
                        }
                    }

                    // 4. mode-specific area
                    Text {
                        Layout.fillWidth: true
                        visible: page.mode === "damage"
                        text: "Scaling stat × (1 + CRIT Rate × CRIT DMG) × (1 + DMG Bonus). CRIT Rate counts up to 100% including the conditional CRIT Rate below."
                        color: Theme.textDim
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: page.mode === "weights"
                        spacing: 6
                        Repeater {
                            model: page.priority
                            delegate: RowLayout {
                                id: wrow
                                required property var modelData
                                spacing: 10
                                Text {
                                    Layout.preferredWidth: 160
                                    text: page.labelOf(wrow.modelData)
                                    color: Theme.text
                                    font.pixelSize: 13
                                }
                                Field {
                                    Layout.preferredWidth: 80
                                    text: String(page.weights[wrow.modelData] ?? 1)
                                    validator: DoubleValidator { locale: "C" }
                                    onEditingFinished: {
                                        const w = Object.assign({}, page.weights)
                                        const v = Number(text)
                                        w[wrow.modelData] = isNaN(v) ? 1 : v
                                        page.weights = w
                                    }
                                }
                            }
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: page.mode === "targets"
                        spacing: 6
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            GhostButton {
                                label: "Use Akasha's top 1% averages"
                                implicitHeight: 32
                                enabledState: !optimizer.busy
                                onClicked: optimizer.akashaTargets(page.scaling)
                            }
                            Text {
                                Layout.fillWidth: true
                                text: optimizer.akashaTop1.calc
                                      ? "Top 1% of " + optimizer.akashaTop1.calc + " (your build: " + optimizer.akashaTop1.rank + ")"
                                      : "Fills the targets with the average stats of the top 1% of this character's Akasha leaderboard."
                                color: Theme.textDim
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                            }
                        }
                        Repeater {
                            model: page.priority
                            delegate: RowLayout {
                                id: trow
                                required property var modelData
                                spacing: 10
                                Text {
                                    Layout.preferredWidth: 160
                                    text: page.labelOf(trow.modelData)
                                    color: Theme.text
                                    font.pixelSize: 13
                                }
                                Field {
                                    Layout.preferredWidth: 80
                                    placeholderText: "e.g. 70"
                                    text: page.targets[trow.modelData] !== undefined ? String(page.targets[trow.modelData]) : ""
                                    validator: DoubleValidator { bottom: 0; locale: "C" }
                                    onEditingFinished: {
                                        const t = Object.assign({}, page.targets)
                                        const v = Number(text)
                                        if (text !== "" && !isNaN(v) && v > 0) t[trow.modelData] = v
                                        else delete t[trow.modelData]
                                        page.targets = t
                                    }
                                }
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "Reaches every target as evenly as possible, then the highest damage estimate."
                            color: Theme.textDim
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: page.mode === "ratio"
                        spacing: 6
                        RowLayout {
                            spacing: 10
                            Combo {
                                Layout.preferredWidth: 170
                                model: page.priority.map(function(k) { return page.labelOf(k) })
                                currentIndex: page.priority.indexOf(page.ratio[0])
                                onActivated: function(i) {
                                    const r = page.ratio.slice(); r[0] = page.priority[i]; page.ratio = r
                                }
                            }
                            Field {
                                Layout.preferredWidth: 60
                                text: String(page.ratio[1])
                                validator: DoubleValidator { bottom: 0; locale: "C" }
                                onEditingFinished: {
                                    const r = page.ratio.slice(); const v = Number(text)
                                    r[1] = isNaN(v) ? 1 : v; page.ratio = r
                                }
                            }
                            Text { text: ":"; color: Theme.text; font.pixelSize: 14 }
                            Field {
                                Layout.preferredWidth: 60
                                text: String(page.ratio[3])
                                validator: DoubleValidator { bottom: 0; locale: "C" }
                                onEditingFinished: {
                                    const r = page.ratio.slice(); const v = Number(text)
                                    r[3] = isNaN(v) ? 1 : v; page.ratio = r
                                }
                            }
                            Combo {
                                Layout.preferredWidth: 170
                                model: page.priority.map(function(k) { return page.labelOf(k) })
                                currentIndex: page.priority.indexOf(page.ratio[2])
                                onActivated: function(i) {
                                    const r = page.ratio.slice(); r[2] = page.priority[i]; page.ratio = r
                                }
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "Keeps the two stats near this ratio (e.g. CRIT Rate : CRIT DMG = 1 : 2), then the highest damage estimate."
                            color: Theme.textDim
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: page.mode === "akasha"
                        spacing: 8
                        Text {
                            Layout.fillWidth: true
                            text: "Pick one of this character's Akasha leaderboards. Lumenspar learns its formula from a sample of it, takes the sets and main stats its top builds use, and finds your best build for it."
                            color: Theme.textDim
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: !!optimizer.akashaBoardsNote
                            text: optimizer.akashaBoardsNote || ""
                            color: Theme.danger
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }
                        Column {
                            Layout.fillWidth: true
                            spacing: 6
                            Repeater {
                                model: page.boards
                                delegate: Rectangle {
                                    id: boardRow
                                    required property var modelData
                                    readonly property bool selected: modelData.calcId === page.boardId
                                    width: parent.width
                                    height: 54
                                    radius: 10
                                    color: Theme.bgAlt
                                    border.width: 1
                                    border.color: selected ? Theme.accent : Theme.border

                                    HoverHandler { id: boardHover; cursorShape: Qt.PointingHandCursor }
                                    TapHandler {
                                        onTapped: {
                                            page.boardId = boardRow.modelData.calcId
                                            page.boardVariant = boardRow.modelData.defaultVariant
                                        }
                                    }
                                    ToolTip.visible: boardHover.hovered && !!modelData.details
                                    ToolTip.delay: 400
                                    ToolTip.text: modelData.details

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 14
                                        anchors.rightMargin: 14
                                        spacing: 10
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 2
                                            RowLayout {
                                                spacing: 8
                                                Text {
                                                    text: boardRow.modelData.name
                                                    color: Theme.text
                                                    font.pixelSize: 13
                                                    font.weight: Font.DemiBold
                                                }
                                                Rectangle {
                                                    visible: !!boardRow.modelData.short
                                                    implicitWidth: shortText.implicitWidth + 12
                                                    implicitHeight: 18
                                                    radius: 9
                                                    color: Theme.surface
                                                    border.width: 1
                                                    border.color: Theme.border
                                                    Text {
                                                        id: shortText
                                                        anchors.centerIn: parent
                                                        text: boardRow.modelData.short
                                                        color: Theme.textDim
                                                        font.pixelSize: 10
                                                    }
                                                }
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                text: boardRow.modelData.weapon
                                                color: Theme.textDim
                                                font.pixelSize: 11
                                                elide: Text.ElideRight
                                            }
                                        }
                                        Text {
                                            text: boardRow.modelData.yourRank
                                            color: Theme.accent
                                            font.pixelSize: 12
                                        }
                                    }
                                }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            visible: page.selectedBoard !== null
                            spacing: 10
                            RowLabel { text: "ER requirement" }
                            Combo {
                                id: variantBox
                                readonly property var variantList: page.selectedBoard ? page.selectedBoard.variants : []
                                Layout.preferredWidth: 240
                                model: ["All builds"].concat(variantList.map(function(v) { return v.label || v.name }))
                                currentIndex: {
                                    for (let i = 0; i < variantList.length; i++)
                                        if (variantList[i].name === page.boardVariant) return i + 1
                                    return 0
                                }
                                onActivated: function(i) {
                                    page.boardVariant = i === 0 ? "" : variantList[i - 1].name
                                }
                            }
                            Item { Layout.fillWidth: true }
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: !!optimizer.akashaInfo
                            text: optimizer.akashaInfo || ""
                            color: Theme.textDim
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: page.mode === "teamdmg"
                        spacing: 8
                        Text {
                            Layout.fillWidth: true
                            text: "Exact damage from the Team & damage tab: its team, conditions and enemy apply. Lumenspar searches your artifacts for the build that maximizes the chosen hit."
                            color: Theme.textDim
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            visible: !page.teamInfo.inTeam
                            spacing: 10
                            Text {
                                text: (page.teamInfo.name || "This character") + " isn't in the team yet."
                                color: Theme.text
                                font.pixelSize: 13
                            }
                            GhostButton {
                                label: "Add to team"
                                implicitHeight: 32
                                onClicked: team.addOwned(optimizer.card.key)
                            }
                            Item { Layout.fillWidth: true }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            visible: !!page.teamInfo.inTeam
                            spacing: 10
                            RowLabel { text: "Target" }
                            Combo {
                                Layout.preferredWidth: 420
                                model: page.teamTargets.map(function(t) { return t.label })
                                currentIndex: {
                                    for (let i = 0; i < page.teamTargets.length; i++)
                                        if (page.teamTargets[i].key === page.teamTarget) return i
                                    return 0
                                }
                                onActivated: function(i) { page.teamChoice = page.teamTargets[i].key }
                            }
                            Item { Layout.fillWidth: true }
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: !!page.teamInfo.inTeam && !page.teamInfo.hasFormulas
                            text: "Open Team & damage and select " + (page.teamInfo.name || "the character") + " once to list their hits."
                            color: Theme.textDim
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }
                    }

                    // 5. main stats
                    Repeater {
                        model: [{ slot: "sands", name: "Sands" }, { slot: "goblet", name: "Goblet" },
                                { slot: "circlet", name: "Circlet" }]
                        delegate: RowLayout {
                            id: mrow
                            required property var modelData
                            Layout.fillWidth: true
                            visible: page.mode !== "akasha"
                            spacing: 10
                            RowLabel { text: mrow.modelData.name + " main stat" }
                            Flow {
                                Layout.fillWidth: true
                                spacing: 8
                                Repeater {
                                    model: (optimizer.mainChoices || {})[mrow.modelData.slot] || []
                                    delegate: Pill {
                                        required property var modelData
                                        label: modelData.label
                                        checked: (page.mains[mrow.modelData.slot] || []).indexOf(modelData.key) >= 0
                                        onClicked: {
                                            const m = Object.assign({}, page.mains)
                                            m[mrow.modelData.slot] = page.toggle(m[mrow.modelData.slot] || [], modelData.key)
                                            page.mains = m
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // 6. set
                    RowLayout {
                        Layout.fillWidth: true
                        visible: page.mode !== "akasha"
                        spacing: 10
                        RowLabel { text: "Set" }
                        Combo {
                            id: setBox
                            readonly property var setList: optimizer.sets || []
                            Layout.preferredWidth: 320
                            model: ["Any set"].concat(setList.map(function(s) { return s.name + " (" + s.count + ")" }))
                            currentIndex: {
                                for (let i = 0; i < setList.length; i++)
                                    if (setList[i].key === page.setKey) return i + 1
                                return 0
                            }
                            onActivated: function(i) {
                                page.setKey = i === 0 ? "" : setList[i - 1].key
                                optimizer.refreshCrit(page.setKey)
                            }
                        }
                        Item { Layout.fillWidth: true }
                    }

                    // 7. minimums
                    RowLayout {
                        Layout.fillWidth: true
                        visible: page.mode !== "akasha"
                        spacing: 10
                        RowLabel { text: "Minimums" }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            Repeater {
                                model: [
                                    { key: "enerRech_", label: "Energy Recharge", values: [110, 120, 130, 140, 160, 180, 200], unit: "%" },
                                    { key: "critRate_", label: "CRIT Rate", values: [50, 60, 70, 80], unit: "%" },
                                    { key: "eleMas", label: "Elemental Mastery", values: [100, 200, 300, 400], unit: "" }]
                                delegate: RowLayout {
                                    id: minRow
                                    required property var modelData
                                    spacing: 8
                                    Text {
                                        Layout.preferredWidth: 130
                                        text: minRow.modelData.label
                                        color: Theme.text
                                        font.pixelSize: 13
                                    }
                                    Flow {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        Pill {
                                            label: "None"
                                            checked: page.minimumOf(minRow.modelData.key) === 0
                                            onClicked: page.setPreset(minRow.modelData.key, 0)
                                        }
                                        Repeater {
                                            model: minRow.modelData.values
                                            delegate: Pill {
                                                required property var modelData
                                                label: modelData + minRow.modelData.unit
                                                checked: page.minimumOf(minRow.modelData.key) === modelData
                                                onClicked: page.setPreset(minRow.modelData.key, modelData)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // 8. conditional crit rate
                    RowLayout {
                        Layout.fillWidth: true
                        visible: page.mode !== "akasha" && page.mode !== "teamdmg"
                        spacing: 10
                        RowLabel { text: "Conditional CRIT Rate" }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            Repeater {
                                model: page.crit.sources || []
                                delegate: Text {
                                    required property var modelData
                                    text: modelData.label + " — " + modelData.value + "%"
                                    color: Theme.text
                                    font.pixelSize: 12
                                }
                            }
                            Text {
                                visible: (page.crit.sources || []).length === 0
                                text: "None found in the weapon passive"
                                color: Theme.textDim
                                font.pixelSize: 12
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: !!page.crit.note
                                text: page.crit.note || ""
                                color: Theme.textDim
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                            }
                            RowLayout {
                                spacing: 10
                                Text {
                                    text: "Extra (team buffs, passives)"
                                    color: Theme.text
                                    font.pixelSize: 12
                                }
                                Repeater {
                                    model: [0, 10, 15, 20, 30, 40]
                                    delegate: Pill {
                                        required property var modelData
                                        label: modelData + "%"
                                        checked: page.extraCrit === modelData
                                        onClicked: page.extraCrit = modelData
                                    }
                                }
                                Text {
                                    text: "Panel CRIT Rate above "
                                          + Math.max(0, 100 - (page.crit.total || 0) - page.extraCrit).toFixed(0)
                                          + "% is wasted"
                                    color: Theme.textDim
                                    font.pixelSize: 12
                                }
                            }
                        }
                    }

                    // 9. artifacts
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        RowLabel { text: "Artifacts" }
                        Text {
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignVCenter
                            text: optimizer.pieceCount + " five-star artifacts from " + optimizer.sourcePath
                            color: Theme.text
                            font.pixelSize: 12
                            elide: Text.ElideMiddle
                        }
                        GhostButton {
                            label: "Choose file…"
                            implicitHeight: 32
                            onClicked: fileDlg.open()
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        RowLabel { text: "" }
                        Pill {
                            label: "Use artifacts other characters wear"
                            checked: page.useEquipped
                            onClicked: page.useEquipped = !page.useEquipped
                        }
                        Text { text: "Minimum level"; color: Theme.textDim; font.pixelSize: 12 }
                        Repeater {
                            model: [0, 4, 8, 12, 16, 20]
                            delegate: Pill {
                                required property var modelData
                                label: "+" + modelData
                                checked: page.minLevel === modelData
                                onClicked: page.minLevel = modelData
                            }
                        }
                        Item { Layout.fillWidth: true }
                    }

                    // 10. run
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 14
                        AccentButton {
                            label: optimizer.busy ? "Stop" : "Optimize"
                            pulsing: optimizer.busy
                            enabledState: optimizer.busy
                                          || (page.mode === "akasha" ? page.boardId !== ""
                                              : (!!optimizer.card && optimizer.card.name !== undefined))
                            onClicked: {
                                if (optimizer.busy) optimizer.stop()
                                else if (page.mode === "akasha") {
                                    page.shown = 0
                                    optimizer.runAkasha(page.boardId, page.boardVariant, page.minLevel, page.useEquipped)
                                }
                                else if (page.mode === "teamdmg") {
                                    page.shown = 0
                                    optimizer.runTeam(page.teamTarget, page.setKey, page.mains,
                                                      page.goal().minimums, page.minLevel, page.useEquipped)
                                }
                                else { page.shown = 0; optimizer.run(page.goal()) }
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: optimizer.status
                            color: Theme.textDim
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }
                    }
                }

                // ── results ───────────────────────────────────────────────
                Card {
                    title: "Results"
                    subtitle: "Best builds from your artifacts. 'from …' marks pieces another character wears."
                    visible: page.results.length > 0 || page.currentCard !== null

                    Flow {
                        Layout.fillWidth: true
                        spacing: 8
                        Pill {
                            visible: page.currentCard !== null
                            label: "Current"
                            checked: page.showCurrent
                            onClicked: page.shown = -1
                        }
                        Repeater {
                            model: page.results
                            delegate: Pill {
                                required property var modelData
                                required property int index
                                label: "#" + modelData.rank + " " + modelData.setName + "  " + modelData.change
                                checked: !page.showCurrent && page.shown === index
                                onClicked: page.shown = index
                            }
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: page.showCurrent
                              ? ((optimizer.current && optimizer.current.scoreText) || "")
                              : (page.entry ? (page.mode === "teamdmg"
                                                 ? (page.entry.scoreText || "") + " (" + page.entry.change + ")"
                                                 : (page.mode === "damage" ? "" : (page.entry.scoreText || "") + "  ·  ")
                                                   + "damage estimate " + page.entry.damageText
                                                   + " (" + page.entry.change + ")") : "")
                        color: Theme.text
                        font.pixelSize: 13
                        wrapMode: Text.WordWrap
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: !page.showCurrent && page.entry !== null
                        spacing: 3
                        Repeater {
                            model: page.entry ? (page.entry.deltas || []) : []
                            delegate: RowLayout {
                                required property var modelData
                                spacing: 10
                                Text {
                                    Layout.preferredWidth: 160
                                    text: modelData.label
                                    color: Theme.textDim
                                    font.pixelSize: 12
                                }
                                Text {
                                    Layout.preferredWidth: 80
                                    text: String(modelData.before)
                                    color: Theme.text
                                    font.pixelSize: 12
                                }
                                Text { text: "→"; color: Theme.textDim; font.pixelSize: 12 }
                                Text {
                                    text: String(modelData.after)
                                    color: modelData.better ? Theme.ok : Theme.danger
                                    font.pixelSize: 12
                                }
                            }
                        }
                    }

                    Item {   // the card, scaled down to fit narrower windows
                        id: holder
                        Layout.fillWidth: true
                        visible: page.shownCard !== null
                        readonly property real fit: Math.min(1, width / resultCard.width)
                        Layout.preferredHeight: resultCard.height * fit
                        BuildCard {
                            id: resultCard
                            c: page.shownCard
                            footer: page.showCurrent ? "Current build" : "Suggested by Lumenspar's optimizer"
                            transformOrigin: Item.TopLeft
                            scale: holder.fit
                        }
                    }
                }
            }

            TeamPanel { Layout.fillWidth: true; visible: page.tab === "team" }
            Item { Layout.preferredHeight: 4 }
        }
    }
}
