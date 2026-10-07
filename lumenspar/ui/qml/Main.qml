import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import Lumenspar

ApplicationWindow {
    id: win
    property bool showKey: false   // the Gemini API-key field's Show/Hide eye toggle
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
                    text: "Genshin Impact inventory scanner · exports .GOOD"
                    color: Theme.textDim
                    font.pixelSize: 12
                }
            }

            Item { Layout.fillWidth: true }

            StatusPill { label: backend.readerMode === "ai" ? "Gemini" : "OCR"; good: backend.readerReady }
            StatusPill { label: backend.matcherBackend.indexOf("rapidfuzz") === 0 ? "rapidfuzz" : "difflib"; good: backend.matcherBackend.indexOf("rapidfuzz") === 0 }
            StatusPill { label: backend.vocabSummary; good: true }
        }
    }

    // ── body ──────────────────────────────────────────────────────────
    // layered backdrop behind the settings/activity columns
    Backdrop {
        anchors.fill: parent
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 18

        // settings column
        ScrollView {
            id: settingsScroll
            objectName: "settingsScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true
            // Always show the scrollbar: several settings live below the fold
            // and there is otherwise no hint that the column scrolls.
            ScrollBar.vertical.policy: ScrollBar.AlwaysOn

            ColumnLayout {
                width: settingsScroll.availableWidth
                spacing: Theme.gap

                Card {
                    title: "What to scan"
                    subtitle: "Pick the inventory categories to read. Artifacts are the slowest and most detailed."
                    Flow {
                        Layout.fillWidth: true
                        spacing: 10
                        CategoryChip {
                            label: "Artifacts"; glyph: "❖"
                            color: Theme.accent   // per-category tint
                            checked: backend.categories.indexOf("artifacts") !== -1
                            onToggled: function(on) { backend.setCategory("artifacts", on) }
                        }
                        CategoryChip {
                            label: "Weapons"; glyph: "⚔"
                            color: Theme.accent2   // per-category tint
                            checked: backend.categories.indexOf("weapons") !== -1
                            onToggled: function(on) { backend.setCategory("weapons", on) }
                        }
                        CategoryChip {
                            label: "Characters"; glyph: "☺"
                            color: "#E8B45A"   // per-category tint
                            checked: backend.categories.indexOf("characters") !== -1
                            onToggled: function(on) { backend.setCategory("characters", on) }
                        }
                        CategoryChip {
                            label: "Materials"; glyph: "✦"
                            color: Theme.ok   // per-category tint
                            checked: backend.categories.indexOf("materials") !== -1
                            onToggled: function(on) { backend.setCategory("materials", on) }
                        }
                    }
                }

                Card {
                    title: "Reader"
                    subtitle: "How the text on each panel is read."
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            spacing: 6
                            ModeChip {
                                label: "Local OCR"; glyph: "▣"
                                color: Theme.accent
                                checked: backend.readerMode === "local"
                                onClicked: backend.readerMode = "local"
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Tesseract on this machine. Offline, free, slower on stylised text."
                                color: Theme.textDim
                                font.pixelSize: 11
                                wrapMode: Text.WordWrap
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            spacing: 6
                            ModeChip {
                                label: "AI (Gemini)"; glyph: "✦"
                                color: Theme.accent2
                                checked: backend.readerMode === "ai"
                                onClicked: backend.readerMode = "ai"
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Google's vision model reads each panel. Needs your own free API key; far better on stylised text."
                                color: Theme.textDim
                                font.pixelSize: 11
                                wrapMode: Text.WordWrap
                            }
                        }
                    }

                    // AI-only settings, collapsed until AI (Gemini) is picked.
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        clip: true
                        Layout.preferredHeight: aiBody.visible ? aiBody.implicitHeight : 0
                        Behavior on Layout.preferredHeight { NumberAnimation { duration: Theme.ease } }
                        ColumnLayout {
                            id: aiBody
                            Layout.fillWidth: true
                            spacing: 10
                            visible: backend.readerMode === "ai"
                            opacity: backend.readerMode === "ai" ? 1.0 : 0.0
                            Behavior on opacity { NumberAnimation { duration: Theme.ease } }
                            Layout.topMargin: 4

                            Text {
                                text: "Gemini API key"
                                color: Theme.text
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10
                                visible: !backend.geminiKeyFromEnv
                                TextField {
                                    id: keyField
                                    Layout.fillWidth: true
                                    text: backend.geminiApiKey
                                    placeholderText: "paste your key from aistudio.google.com/apikey"
                                    echoMode: win.showKey ? TextInput.Normal : TextInput.Password
                                    enabled: !backend.geminiKeyFromEnv
                                    color: Theme.text
                                    font.pixelSize: 13
                                    onEditingFinished: backend.geminiApiKey = text.trim()
                                    background: Rectangle {
                                        radius: 8; color: Theme.bgAlt
                                        border.color: keyField.activeFocus ? Theme.accent : Theme.border
                                        border.width: 1
                                        Rectangle {   // outer focus glow
                                            anchors.fill: parent
                                            anchors.margins: -3
                                            radius: 11
                                            color: "transparent"
                                            border.color: Qt.rgba(0.31, 0.847, 0.91, keyField.activeFocus ? 0.4 : 0)
                                            border.width: 1
                                            Behavior on border.color { ColorAnimation { duration: Theme.ease } }
                                        }
                                    }
                                }
                                GhostButton {
                                    label: win.showKey ? "Hide" : "Show"
                                    enabledState: !backend.geminiKeyFromEnv
                                    Layout.preferredWidth: 76
                                    onClicked: win.showKey = !win.showKey
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: backend.geminiKeyFromEnv
                                text: "Using the key from LUMENSPAR_GEMINI_KEY"
                                color: Theme.textDim
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                text: "Model"
                                color: Theme.text
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                                Layout.topMargin: 2
                            }
                            TextField {
                                id: modelField
                                text: backend.geminiModel
                                placeholderText: "gemini-3.5-flash-lite"
                                Layout.fillWidth: true
                                color: Theme.text
                                font.pixelSize: 13
                                onEditingFinished: backend.geminiModel = text.trim()
                                background: Rectangle {
                                    radius: 8; color: Theme.bgAlt
                                    border.color: modelField.activeFocus ? Theme.accent : Theme.border
                                    border.width: 1
                                    Rectangle {   // outer focus glow
                                        anchors.fill: parent
                                        anchors.margins: -3
                                        radius: 11
                                        color: "transparent"
                                        border.color: Qt.rgba(0.31, 0.847, 0.91, modelField.activeFocus ? 0.4 : 0)
                                        border.width: 1
                                        Behavior on border.color { ColorAnimation { duration: Theme.ease } }
                                    }
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Flash-Lite has the roomiest free quota. Model names change -- if the self-test says the model does not exist, check aistudio.google.com for the current Flash-Lite id."
                                color: Theme.textDim
                                font.pixelSize: 11
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                Layout.fillWidth: true
                                text: "• Free keys are rate-limited (roughly 15 requests a minute and a few hundred a day for Flash-Lite). Lumenspar sends 6 panels per request, so a typical inventory is about 60-100 requests."
                                color: Theme.textDim
                                font.pixelSize: 11
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "• Only cropped item panels and character pages are sent -- never your UID or the full screen."
                                color: Theme.textDim
                                font.pixelSize: 11
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "• Google may use free-tier requests to improve its models (not in the EEA/UK/CH). Use a paid key if that matters to you."
                                color: Theme.textDim
                                font.pixelSize: 11
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                text: "Get a free key"
                                color: Theme.accent
                                font.pixelSize: 12
                                font.underline: true
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: Qt.openUrlExternally("https://aistudio.google.com/apikey")
                                }
                            }
                        }
                    }
                }

                Card {
                    title: "Characters from Enka.Network"
                    subtitle: "Exact character data from your in-game profile showcase, instead of reading it off the screen. Turn on \"Show Character Details\" in your profile. To collect everyone, rotate characters through the showcase: after each change, exit to the title screen and back so the game publishes it."
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        TextField {
                            id: uidField
                            text: backend.uid
                            placeholderText: "Your UID"
                            Layout.preferredWidth: 150
                            color: Theme.text
                            font.pixelSize: 13
                            inputMethodHints: Qt.ImhDigitsOnly
                            onEditingFinished: backend.uid = text.trim()
                            background: Rectangle {
                                radius: 8; color: Theme.bgAlt
                                border.color: uidField.activeFocus ? Theme.accent : Theme.border
                                border.width: 1
                                Rectangle {   // outer focus glow
                                    anchors.fill: parent
                                    anchors.margins: -3
                                    radius: 11
                                    color: "transparent"
                                    border.color: Qt.rgba(0.31, 0.847, 0.91, uidField.activeFocus ? 0.4 : 0)
                                    border.width: 1
                                    Behavior on border.color { ColorAnimation { duration: Theme.ease } }
                                }
                            }
                        }
                        GhostButton {
                            label: "Fetch showcase"
                            enabledState: !backend.scanning
                            onClicked: { backend.uid = uidField.text.trim(); backend.fetchShowcase() }
                        }
                        GhostButton {
                            label: backend.watching ? "Stop watching" : "Watch showcase"
                            onClicked: { backend.uid = uidField.text.trim(); backend.setWatching(!backend.watching) }
                        }
                        Item { Layout.fillWidth: true }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        Text {
                            text: backend.rosterCount === 1 ? "1 character collected"
                                                             : backend.rosterCount + " characters collected"
                            color: Theme.textDim
                            font.pixelSize: 12
                        }
                        Item { Layout.fillWidth: true }
                        GhostButton {
                            label: "Write to export file"
                            enabledState: backend.rosterCount > 0 && !backend.scanning
                            onClicked: backend.exportRoster()
                        }
                        GhostButton {
                            label: "Clear"
                            enabledState: backend.rosterCount > 0 && !backend.scanning
                            onClicked: backend.clearRoster()
                        }
                    }
                }

                Card {
                    title: "Minimum rarity"
                    subtitle: "Anything below these thresholds is skipped, which shortens the scan considerably."
                    GridLayout {
                        columns: 2
                        columnSpacing: 28
                        rowSpacing: 12
                        Layout.fillWidth: true

                        Text { text: "Artifacts"; color: Theme.textDim; font.pixelSize: 13 }
                        StarPicker {
                            value: backend.minArtifactRarity
                            minimum: 1
                            onPicked: function(v) { backend.minArtifactRarity = v }
                        }
                        Text { text: "Weapons"; color: Theme.textDim; font.pixelSize: 13 }
                        StarPicker {
                            value: backend.minWeaponRarity
                            minimum: 1
                            onPicked: function(v) { backend.minWeaponRarity = v }
                        }
                    }
                }

                Card {
                    title: "Scan speed"
                    subtitle: "The scanner waits for each panel to stop changing before reading it. This sets how long it is willing to wait, and how long it pauses between steps."
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 14
                        Slider {
                            id: speed
                            Layout.fillWidth: true
                            from: 0.5; to: 3.0; stepSize: 0.05
                            value: backend.delayScale
                            onMoved: backend.delayScale = value

                            background: Rectangle {
                                x: speed.leftPadding
                                y: speed.topPadding + speed.availableHeight / 2 - 3
                                width: speed.availableWidth; height: 6; radius: 3
                                color: Theme.surfaceHi
                                Rectangle {
                                    width: speed.visualPosition * parent.width
                                    height: parent.height; radius: 3
                                    gradient: Gradient {
                                        orientation: Gradient.Horizontal
                                        GradientStop { position: 0.0; color: Theme.accent }
                                        GradientStop { position: 1.0; color: Theme.accent2 }
                                    }
                                }
                            }
                            handle: Rectangle {
                                x: speed.leftPadding + speed.visualPosition * (speed.availableWidth - width)
                                y: speed.topPadding + speed.availableHeight / 2 - height / 2
                                width: 20; height: 20; radius: 10
                                color: Theme.accent
                                border.color: Qt.rgba(0.31, 0.847, 0.91, 0.6)
                                border.width: 2
                                Rectangle {   // soft accent glow around the handle
                                    anchors.centerIn: parent
                                    width: 26; height: 26; radius: 13
                                    color: Qt.rgba(0.31, 0.847, 0.91, 0.28)
                                }
                            }
                        }
                        Text {
                            text: backend.delayScale.toFixed(2) + "×"
                            color: Theme.accent
                            font.pixelSize: 14
                            font.weight: Font.DemiBold
                            Layout.preferredWidth: 52
                        }
                    }
                    Text {
                        text: backend.delayScale < 0.9 ? "Impatient — only if your machine keeps up."
                            : backend.delayScale > 1.6 ? "Patient. Use this if artifacts are being reported unreadable."
                            : "Balanced default."
                        color: Theme.textDim
                        font.pixelSize: 12
                    }
                }

                Card {
                    title: "Export"
                    subtitle: "A single .GOOD JSON file, importable by Genshin Optimizer, SEELIE.me and Aspirine's calculator."
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        Rectangle {
                            Layout.fillWidth: true
                            height: 38
                            radius: 9
                            color: Theme.bgAlt
                            border.color: Theme.border
                            border.width: 1
                            Text {
                                anchors.fill: parent
                                anchors.leftMargin: 12
                                verticalAlignment: Text.AlignVCenter
                                text: backend.exportPath
                                color: Theme.textDim
                                font.pixelSize: 12
                                elide: Text.ElideMiddle
                            }
                        }
                        GhostButton {
                            label: "Choose folder…"
                            onClicked: folderDialog.open()
                        }
                    }
                }

                Card {
                    title: "Game controls"
                    subtitle: "Must match your in-game keybinds. Control type has to be set to Keyboard, and the game run fullscreen at 16:9 or 16:10."
                    GridLayout {
                        columns: 4
                        columnSpacing: 12
                        rowSpacing: 10
                        Layout.fillWidth: true

                        Text { text: "Inventory"; color: Theme.textDim; font.pixelSize: 13 }
                        TextField {
                            id: invKey
                            text: backend.keyInventory
                            maximumLength: 8
                            implicitWidth: 74
                            color: Theme.text
                            font.pixelSize: 13
                            horizontalAlignment: Text.AlignHCenter
                            onEditingFinished: backend.keyInventory = text.toLowerCase()
                            background: Rectangle {
                                radius: 8; color: Theme.bgAlt
                                border.color: invKey.activeFocus ? Theme.accent : Theme.border
                                border.width: 1
                                Rectangle {   // outer focus glow
                                    anchors.fill: parent
                                    anchors.margins: -3
                                    radius: 11
                                    color: "transparent"
                                    border.color: Qt.rgba(0.31, 0.847, 0.91, invKey.activeFocus ? 0.4 : 0)
                                    border.width: 1
                                    Behavior on border.color { ColorAnimation { duration: Theme.ease } }
                                }
                            }
                        }
                        Text { text: "Character"; color: Theme.textDim; font.pixelSize: 13 }
                        TextField {
                            id: chrKey
                            text: backend.keyCharacter
                            maximumLength: 8
                            implicitWidth: 74
                            color: Theme.text
                            font.pixelSize: 13
                            horizontalAlignment: Text.AlignHCenter
                            onEditingFinished: backend.keyCharacter = text.toLowerCase()
                            background: Rectangle {
                                radius: 8; color: Theme.bgAlt
                                border.color: chrKey.activeFocus ? Theme.accent : Theme.border
                                border.width: 1
                                Rectangle {   // outer focus glow
                                    anchors.fill: parent
                                    anchors.margins: -3
                                    radius: 11
                                    color: "transparent"
                                    border.color: Qt.rgba(0.31, 0.847, 0.91, chrKey.activeFocus ? 0.4 : 0)
                                    border.width: 1
                                    Behavior on border.color { ColorAnimation { duration: Theme.ease } }
                                }
                            }
                        }
                    }

                    Text {
                        text: "Tab keys: " + backend.keyTabLeft.toUpperCase() + " / "
                              + backend.keyTabRight.toUpperCase()
                              + " move between inventory tabs. Lumenspar uses them to switch tabs for you."
                        color: Theme.textDim
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }

                    Text {
                        text: "Your Traveler's name"
                        color: Theme.text
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        Layout.topMargin: 4
                    }
                    Text {
                        text: "You name the Traveler yourself, so it can't be recognised from a list. Leave blank if you never equip gear on them."
                        color: Theme.textDim
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                    TextField {
                        id: travName
                        text: backend.travelerName
                        placeholderText: "e.g. Aether, Lumine, or whatever you named them"
                        Layout.fillWidth: true
                        color: Theme.text
                        font.pixelSize: 13
                        onEditingFinished: backend.travelerName = text.trim()
                        background: Rectangle {
                            radius: 8; color: Theme.bgAlt
                            border.color: travName.activeFocus ? Theme.accent : Theme.border
                            border.width: 1
                            Rectangle {   // outer focus glow
                                anchors.fill: parent
                                anchors.margins: -3
                                radius: 11
                                color: "transparent"
                                border.color: Qt.rgba(0.31, 0.847, 0.91, travName.activeFocus ? 0.4 : 0)
                                border.width: 1
                                Behavior on border.color { ColorAnimation { duration: Theme.ease } }
                            }
                        }
                    }

                    Text {
                        text: "Your Wanderer's name"
                        color: Theme.text
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        Layout.topMargin: 4
                    }
                    Text {
                        text: "Only needed if you renamed the Wanderer in-game. Leave blank if it still shows as \"Wanderer\"."
                        color: Theme.textDim
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                    TextField {
                        id: wandName
                        text: backend.wandererName
                        placeholderText: "e.g. whatever you renamed them to"
                        Layout.fillWidth: true
                        color: Theme.text
                        font.pixelSize: 13
                        onEditingFinished: backend.wandererName = text.trim()
                        background: Rectangle {
                            radius: 8; color: Theme.bgAlt
                            border.color: wandName.activeFocus ? Theme.accent : Theme.border
                            border.width: 1
                            Rectangle {   // outer focus glow
                                anchors.fill: parent
                                anchors.margins: -3
                                radius: 11
                                color: "transparent"
                                border.color: Qt.rgba(0.31, 0.847, 0.91, wandName.activeFocus ? 0.4 : 0)
                                border.width: 1
                                Behavior on border.color { ColorAnimation { duration: Theme.ease } }
                            }
                        }
                    }

                    Text {
                        text: "Other renamed characters"
                        color: Theme.text
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        Layout.topMargin: 4
                    }
                    Text {
                        text: "Names you gave your Manekins, comma-separated. They can't be exported, but listing them lets a name one glyph away from your Traveler's be refused instead of misassigned."
                        color: Theme.textDim
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                    TextField {
                        id: otherNames
                        text: backend.otherNames
                        placeholderText: "e.g. Gal1, galgoit"
                        Layout.fillWidth: true
                        color: Theme.text
                        font.pixelSize: 13
                        onEditingFinished: backend.otherNames = text.trim()
                        background: Rectangle {
                            radius: 8; color: Theme.bgAlt
                            border.color: otherNames.activeFocus ? Theme.accent : Theme.border
                            border.width: 1
                            Rectangle {   // outer focus glow
                                anchors.fill: parent
                                anchors.margins: -3
                                radius: 11
                                color: "transparent"
                                border.color: Qt.rgba(0.31, 0.847, 0.91, otherNames.activeFocus ? 0.4 : 0)
                                border.width: 1
                                Behavior on border.color { ColorAnimation { duration: Theme.ease } }
                            }
                        }
                    }
                }

                Card {
                    title: "Capture"
                    subtitle: "Lumenspar streams the screen through the desktop portal. The picker is shown once, then remembered."
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        GhostButton { label: "Re-pick screen"; onClicked: backend.repickScreen() }
                        GhostButton { label: "Run self-test"; enabledState: !backend.scanning; onClicked: backend.selfTest() }
                        Item { Layout.fillWidth: true }
                    }
                }

                Item { Layout.preferredHeight: 4 }
            }
        }

        // activity column
        Rectangle {
            Layout.preferredWidth: 380
            Layout.fillHeight: true
            color: Theme.surface
            radius: Theme.radius
            border.color: Theme.border
            border.width: 1

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.pad
                spacing: 12

                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "Activity"; color: Theme.text; font.pixelSize: 15; font.weight: Font.DemiBold }
                    Item { Layout.fillWidth: true }
                    BusyIndicator { running: backend.scanning; visible: backend.scanning; implicitWidth: 20; implicitHeight: 20 }
                }

                // slim scanning strip: an animated bar sweeps across while scanning
                Rectangle {
                    id: scanStrip
                    Layout.fillWidth: true
                    Layout.preferredHeight: 3
                    Layout.topMargin: -4
                    Layout.bottomMargin: -9
                    radius: 1.5
                    color: backend.scanning ? Qt.rgba(1, 1, 1, 0.05) : "transparent"
                    clip: true
                    Rectangle {   // sweeping gradient bar
                        id: scanBar
                        width: 120; height: parent.height; radius: 1.5
                        x: -120
                        visible: backend.scanning
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: Theme.accent }
                            GradientStop { position: 1.0; color: Theme.accent2 }
                        }
                        NumberAnimation on x {
                            from: -120; to: scanStrip.width
                            duration: 1300
                            loops: Animation.Infinite
                            running: backend.scanning
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: 10
                    color: Theme.bg
                    border.color: Theme.border
                    border.width: 1
                    Rectangle {   // inner border for the console feel
                        anchors.fill: parent
                        anchors.margins: 1
                        radius: 9
                        color: "transparent"
                        border.color: Qt.rgba(1, 1, 1, 0.05)
                        border.width: 1
                    }

                    ListView {
                        id: logView
                        anchors.fill: parent
                        anchors.margins: 10
                        clip: true
                        model: logModel
                        spacing: 2
                        onCountChanged: positionViewAtEnd()
                        delegate: Text {
                            required property string line
                            width: logView.width
                            text: line
                            color: line.indexOf("error") === 0 ? Theme.danger
                                 : line.indexOf("──") === 0 ? Theme.accent : Theme.textDim
                            font.family: "monospace"
                            font.pixelSize: 12
                            wrapMode: Text.WrapAnywhere
                        }
                    }

                    Column {
                        anchors.centerIn: parent
                        visible: logModel.count === 0
                        spacing: 8
                        Text {   // faint crystal glyph
                            text: "◆"
                            color: Qt.rgba(0.31, 0.847, 0.91, 0.30)
                            font.pixelSize: 22
                            anchors.horizontalCenter: parent.horizontalCenter
                        }
                        Text {
                            text: "Run a self-test to check\ncapture and OCR."
                            horizontalAlignment: Text.AlignHCenter
                            color: Theme.textDim
                            font.pixelSize: 12
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: backend.status
                    color: Theme.textDim
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                    visible: text !== ""
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    GhostButton { label: "Save"; onClicked: backend.save() }
                    Item { Layout.fillWidth: true }
                    AccentButton {
                        label: backend.scanning ? "Stop" : "Start scan"
                        pulsing: backend.scanning
                        onClicked: backend.scanning ? backend.stopScan() : backend.startScan()
                    }
                }
            }
        }
    }

    ListModel { id: logModel }

    FolderDialog {
        id: folderDialog
        title: "Choose export folder"
        onAccepted: backend.setExportDirFromUrl(selectedFolder.toString())
    }

    Connections {
        target: backend
        function onLogAppended(line) { logModel.append({ line: line }) }
    }
}
