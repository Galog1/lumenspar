import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import Lumenspar

ApplicationWindow {
    id: win
    width: 1180
    height: 800
    minimumWidth: 940
    minimumHeight: 640
    visible: true
    title: "Lumenspar"
    color: Theme.bg

    // ── header ────────────────────────────────────────────────────────
    header: Rectangle {
        height: 74
        color: Theme.bgAlt
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 24
            anchors.rightMargin: 24
            spacing: 16

            Rectangle {
                width: 34; height: 34; radius: 9
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: Theme.accent }
                    GradientStop { position: 1.0; color: Theme.accent2 }
                }
                Text { anchors.centerIn: parent; text: "◆"; font.pixelSize: 16; color: "#08121A" }
            }

            ColumnLayout {
                spacing: 0
                Text {
                    text: "LUMENSPAR"
                    color: Theme.text
                    font.pixelSize: 17
                    font.weight: Font.Bold
                    font.letterSpacing: 2.4
                }
                Text {
                    text: "Genshin Impact inventory scanner · exports .GOOD"
                    color: Theme.textDim
                    font.pixelSize: 12
                }
            }

            Item { Layout.fillWidth: true }

            StatusPill { label: backend.ocrReady ? "Tesseract ready" : "Tesseract missing"; good: backend.ocrReady }
            StatusPill { label: backend.matcherBackend.indexOf("rapidfuzz") === 0 ? "rapidfuzz" : "difflib"; good: backend.matcherBackend.indexOf("rapidfuzz") === 0 }
            StatusPill { label: backend.vocabSummary; good: true }
        }
    }

    // ── body ──────────────────────────────────────────────────────────
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
                            checked: backend.categories.indexOf("artifacts") !== -1
                            onToggled: function(on) { backend.setCategory("artifacts", on) }
                        }
                        CategoryChip {
                            label: "Weapons"; glyph: "⚔"
                            checked: backend.categories.indexOf("weapons") !== -1
                            onToggled: function(on) { backend.setCategory("weapons", on) }
                        }
                        CategoryChip {
                            label: "Characters"; glyph: "☺"
                            checked: backend.categories.indexOf("characters") !== -1
                            onToggled: function(on) { backend.setCategory("characters", on) }
                        }
                        CategoryChip {
                            label: "Materials"; glyph: "✦"
                            checked: backend.categories.indexOf("materials") !== -1
                            onToggled: function(on) { backend.setCategory("materials", on) }
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
                                color: Theme.text
                                border.color: Theme.accent
                                border.width: 2
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

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: 10
                    color: Theme.bg
                    border.color: Theme.border
                    border.width: 1

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

                    Text {
                        anchors.centerIn: parent
                        visible: logModel.count === 0
                        text: "Run a self-test to check\ncapture and OCR."
                        horizontalAlignment: Text.AlignHCenter
                        color: Theme.textDim
                        font.pixelSize: 12
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
