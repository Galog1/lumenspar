import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window
import QtWebEngine
import Lumenspar

// The HoYoLAB sign-in window. HoYoLAB's character endpoints answer only to a
// signed-in session, so the player signs in on HoYoLAB's own page here and
// presses "Fetch my characters"; the requests then run from a HoYoLAB page
// (hoyolab.fetchScript). The profile is off the record: cookies and all other
// site data stay in memory and vanish when this window is destroyed, so the
// sign-in is never written to disk. Nothing here reads form fields, cookies
// or storage. Loaded only while hoyolab.open, by a Loader in BuildsPage.
Window {
    id: win
    width: 1000
    height: 780
    visible: true
    title: "Sign in to HoYoLAB"
    color: Theme.bg

    property bool pending: false      // loading the page the requests run from
    property bool polling: false
    readonly property bool profileOtr: otrProfile.offTheRecord
    property int lost: 0              // polls that found no script state (page replaced)

    onClosing: hoyolab.cancel()

    WebEngineProfile {
        id: otrProfile
        offTheRecord: true
    }

    function fetchCharacters() {
        hoyolab.fetchNow()
        win.pending = true
        web.url = hoyolab.actUrl
    }

    function startScript() {
        const url = web.url.toString()
        if (url.indexOf("://act.hoyolab.com") < 0) {
            // Sent to a sign-in page instead: the session is not valid yet.
            hoyolab.failed("not signed in", 10001)
            web.url = hoyolab.loginUrl
            return
        }
        win.lost = 0
        web.runJavaScript(hoyolab.fetchScript, function () { win.polling = true })
    }

    Timer {
        interval: 500
        repeat: true
        running: win.polling
        onTriggered: web.runJavaScript(hoyolab.progressJs, function (json) {
            if (!win.polling) return
            if (!json || json === "null") {
                if (++win.lost > 20) {
                    win.polling = false
                    hoyolab.failed("the page was replaced while reading", 0)
                    web.url = hoyolab.loginUrl
                }
                return
            }
            win.lost = 0
            hoyolab.progress(json)
            const p = JSON.parse(json)
            if (!p.finished) return
            win.polling = false
            if (p.error) {
                hoyolab.failed(p.error, p.retcode)
                web.url = hoyolab.loginUrl
            } else {
                web.runJavaScript(hoyolab.resultJs, function (res) { hoyolab.finish(res) })
            }
        })
    }

    Component {
        id: popupWindow
        Window {
            id: pw
            property alias view: popupView
            width: 520
            height: 720
            visible: true
            title: popupView.title
            color: "white"
            transientParent: win
            WebEngineView {
                id: popupView
                anchors.fill: parent
                profile: otrProfile
                onNewWindowRequested: (request) => {
                    const popup = popupWindow.createObject(win)
                    request.openIn(popup.view)
                }
                onWindowCloseRequested: pw.close()
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: bar.implicitHeight + 24
            color: Theme.surfaceGlass
            RowLayout {
                id: bar
                anchors.fill: parent
                anchors.margins: 12
                spacing: 14
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Text {
                        Layout.fillWidth: true
                        text: hoyolab.status
                        color: Theme.text
                        font.pixelSize: 13
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "Your password goes to HoYoLAB only. Lumenspar does not read it, and nothing about this sign-in is saved: closing this window forgets it."
                        color: Theme.textDim
                        font.pixelSize: 11
                        wrapMode: Text.WordWrap
                    }
                }
                AccentButton {
                    label: hoyolab.step === "fetching" ? "Reading…" : "Fetch my characters"
                    pulsing: hoyolab.step === "fetching"
                    enabledState: hoyolab.step === "login"
                    onClicked: win.fetchCharacters()
                }
                GhostButton {
                    label: "Cancel"
                    onClicked: hoyolab.cancel()
                }
            }
        }

        WebEngineView {
            id: web
            Layout.fillWidth: true
            Layout.fillHeight: true
            profile: otrProfile
            url: hoyolab.loginUrl
            // Sign-in steps (security check, social logins) open popups that
            // report back to this page through window.opener: each gets a
            // real window on the same off-the-record profile, never this view.
            onNewWindowRequested: (request) => {
                const popup = popupWindow.createObject(win)
                request.openIn(popup.view)
            }
            onLoadingChanged: (loadRequest) => {
                if (win.pending && loadRequest.status === WebEngineView.LoadSucceededStatus) {
                    win.pending = false
                    win.startScript()
                } else if (win.pending && loadRequest.status === WebEngineView.LoadFailedStatus) {
                    win.pending = false
                    hoyolab.failed("the HoYoLAB page did not load", 0)
                }
            }
        }
    }
}
