pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

ApplicationWindow {
    id: root

    required property var backend
    width: 1480
    height: 900
    minimumWidth: 1180
    minimumHeight: 720
    visible: true
    color: "transparent"
    title: "Prompt2CST — RF Design Studio"

    property color ink: "#F4F9FF"
    property color muted: "#8FA6BE"
    property color cyan: "#55D7FF"
    property color violet: "#9E8CFF"
    property color amber: "#FFB86B"
    property bool compactHeight: height < 860
    property bool compactWidth: width < 1320
    property int pageMargin: compactHeight ? 14 : 22
    property int sectionGap: compactHeight ? 10 : 16
    property int activeReviewTab: 0
    property string approvalTool: ""
    property string approvalArguments: ""
    property string approvalPreview: ""
    property string infoTitle: ""
    property string infoText: ""

    onClosing: root.backend.cancelPendingApproval()

    Rectangle {
        anchors.fill: parent
        color: "#07101B"
        opacity: 0.97
    }

    Canvas {
        id: fieldCanvas
        anchors.fill: parent
        opacity: 0.25

        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            ctx.lineWidth = 1;

            ctx.strokeStyle = "rgba(65, 180, 235, 0.14)";
            for (var r = 90; r < 740; r += 82) {
                ctx.beginPath();
                ctx.arc(width * 0.08, height * 0.78, r, -1.25, 0.42);
                ctx.stroke();
            }

            ctx.strokeStyle = "rgba(151, 125, 255, 0.08)";
            for (var x = 0; x < width; x += 72) {
                ctx.beginPath();
                ctx.moveTo(x, 0);
                ctx.lineTo(x + 210, height);
                ctx.stroke();
            }
        }
    }

    Rectangle {
        id: cyanOrb
        width: 420
        height: 420
        radius: 210
        x: root.width * 0.48
        y: -260
        color: Qt.rgba(0.08, 0.60, 0.88, 0.075)

        SequentialAnimation on x {
            loops: Animation.Infinite
            NumberAnimation {
                to: root.width * 0.61
                duration: 15000
                easing.type: Easing.InOutSine
            }
            NumberAnimation {
                to: root.width * 0.48
                duration: 15000
                easing.type: Easing.InOutSine
            }
        }
    }

    Rectangle {
        width: 360
        height: 360
        radius: 180
        x: root.width - 210
        y: root.height - 250
        color: Qt.rgba(0.55, 0.33, 0.94, 0.06)

        SequentialAnimation on y {
            loops: Animation.Infinite
            NumberAnimation {
                to: root.height - 330
                duration: 13000
                easing.type: Easing.InOutSine
            }
            NumberAnimation {
                to: root.height - 250
                duration: 13000
                easing.type: Easing.InOutSine
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: root.pageMargin
        spacing: root.compactWidth ? 14 : 18

        GlassPanel {
            id: rail
            Layout.preferredWidth: root.compactWidth ? 218 : 250
            Layout.minimumWidth: root.compactWidth ? 204 : 228
            Layout.fillHeight: true
            glassColor: Qt.rgba(0.045, 0.075, 0.12, 0.88)
            edgeColor: Qt.rgba(0.42, 0.78, 0.98, 0.22)

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: root.compactHeight ? 18 : 22
                spacing: root.compactHeight ? 14 : 18

                RowLayout {
                    spacing: 12

                    Rectangle {
                        Layout.preferredWidth: 48
                        Layout.preferredHeight: 48
                        radius: 16
                        gradient: Gradient {
                            GradientStop {
                                position: 0
                                color: "#16B9E9"
                            }
                            GradientStop {
                                position: 1
                                color: "#635BDB"
                            }
                        }

                        Text {
                            anchors.centerIn: parent
                            text: "P²"
                            color: "white"
                            font.pixelSize: 18
                            font.bold: true
                        }
                    }

                    ColumnLayout {
                        spacing: 1
                        Text {
                            text: "Prompt2CST"
                            color: root.ink
                            font.pixelSize: 20
                            font.weight: Font.DemiBold
                        }
                        Text {
                            text: "RF DESIGN STUDIO"
                            color: root.cyan
                            font.pixelSize: 9
                            font.letterSpacing: 1.6
                            font.weight: Font.DemiBold
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 1
                    color: Qt.rgba(0.7, 0.85, 1.0, 0.12)
                }

                Text {
                    text: "WORKFLOW"
                    color: root.muted
                    font.pixelSize: 10
                    font.letterSpacing: 1.7
                    font.weight: Font.DemiBold
                }

                Repeater {
                    model: [["01", "Describe", "Frequency, geometry and feed"], ["02", "Preview",
                                                                                 "Validate before CST writes"],
                        ["03", "Review", "Inspect parameters and warnings"], ["04", "Build",
                                                                              "Approve the exact CST action"]]

                    RowLayout {
                        id: workflowRow
                        required property var modelData
                        spacing: 12

                        Rectangle {
                            Layout.preferredWidth: 34
                            Layout.preferredHeight: 34
                            radius: 12
                            color: Qt.rgba(0.18, 0.52, 0.75, 0.16)
                            border.width: 1
                            border.color: Qt.rgba(0.36, 0.78, 0.98, 0.25)

                            Text {
                                anchors.centerIn: parent
                                text: workflowRow.modelData[0]
                                color: root.cyan
                                font.pixelSize: 10
                                font.weight: Font.DemiBold
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1
                            Text {
                                text: workflowRow.modelData[1]
                                color: root.ink
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                            }
                            Text {
                                Layout.fillWidth: true
                                text: workflowRow.modelData[2]
                                color: root.muted
                                font.pixelSize: 10
                                elide: Text.ElideRight
                            }
                        }
                    }
                }

                Item {
                    Layout.fillHeight: true
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 120
                    radius: 20
                    color: Qt.rgba(0.06, 0.14, 0.21, 0.86)
                    border.width: 1
                    border.color: Qt.rgba(0.31, 0.82, 0.95, 0.18)

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 7
                        RowLayout {
                            Rectangle {
                                Layout.preferredWidth: 9
                                Layout.preferredHeight: 9
                                radius: 5
                                color: "#55E6A5"
                            }
                            Text {
                                text: "SAFE ENGINE"
                                color: "#8FF2C6"
                                font.pixelSize: 10
                                font.letterSpacing: 1.2
                                font.weight: Font.DemiBold
                            }
                        }
                        Text {
                            text: "20 typed MCP tools"
                            color: root.ink
                            font.pixelSize: 14
                            font.weight: Font.DemiBold
                        }
                        Text {
                            text: "Solver locked · preview required · native approval"
                            color: root.muted
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "v" + root.backend.version
                        color: root.muted
                        font.pixelSize: 11
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                    Text {
                        text: "CST 2026"
                        color: root.cyan
                        font.pixelSize: 11
                    }
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: root.sectionGap

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: root.compactHeight ? 56 : 70
                spacing: 14

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3
                    Text {
                        text: "Antenna intelligence workspace"
                        color: root.ink
                        font.pixelSize: root.compactHeight ? 23 : 26
                        font.weight: Font.DemiBold
                    }
                    Text {
                        text: "Translate RF intent into reviewable CST geometry"
                        color: root.muted
                        font.pixelSize: 13
                    }
                }

                Rectangle {
                    implicitWidth: statusRow.implicitWidth + 30
                    implicitHeight: 40
                    radius: 20
                    color: Qt.rgba(0.06, 0.14, 0.21, 0.78)
                    border.width: 1
                    border.color: Qt.rgba(0.38, 0.79, 0.98, 0.20)

                    RowLayout {
                        id: statusRow
                        anchors.centerIn: parent
                        spacing: 8
                        Rectangle {
                            Layout.preferredWidth: 8
                            Layout.preferredHeight: 8
                            radius: 4
                            color: root.backend.busy ? root.amber : "#55E6A5"

                            SequentialAnimation on opacity {
                                running: root.backend.busy
                                loops: Animation.Infinite
                                NumberAnimation {
                                    to: 0.25
                                    duration: 620
                                }
                                NumberAnimation {
                                    to: 1.0
                                    duration: 620
                                }
                            }
                        }
                        Text {
                            text: root.backend.status
                            color: root.ink
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                        }
                    }
                }
            }

            GlassPanel {
                Layout.fillWidth: true
                Layout.preferredHeight: root.compactHeight ? 104 : 128
                cornerRadius: 24

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: root.compactHeight ? 14 : 18
                    spacing: root.compactHeight ? 10 : 14

                    ColumnLayout {
                        Layout.preferredWidth: 260
                        Layout.fillWidth: true
                        spacing: 7
                        Text {
                            text: "OPENROUTER KEY"
                            color: root.muted
                            font.pixelSize: 10
                            font.letterSpacing: 1.4
                            font.weight: Font.DemiBold
                        }
                        TextField {
                            id: apiKey
                            Layout.fillWidth: true
                            implicitHeight: root.compactHeight ? 44 : 48
                            placeholderText: "sk-or-v1…  ·  memory only"
                            echoMode: revealKey.checked ? TextInput.Normal : TextInput.Password
                            color: root.ink
                            placeholderTextColor: "#60758C"
                            leftPadding: 16
                            rightPadding: 52
                            font.pixelSize: 13

                            background: Rectangle {
                                radius: 16
                                color: Qt.rgba(0.025, 0.055, 0.09, 0.82)
                                border.width: 1
                                border.color: apiKey.activeFocus ? root.cyan : Qt.rgba(0.55, 0.74, 0.93,
                                                                                       0.18)
                                Behavior on border.color {
                                    ColorAnimation {
                                        duration: 160
                                    }
                                }
                            }

                            AbstractButton {
                                id: revealKey
                                anchors.right: parent.right
                                anchors.rightMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                width: 34
                                height: 28
                                implicitWidth: 34
                                implicitHeight: 28
                                checkable: true
                                hoverEnabled: true
                                Accessible.name: checked ? "Hide OpenRouter key" :
                                                          "Show OpenRouter key"
                                ToolTip.visible: hovered
                                ToolTip.text: checked ? "Hide API key" : "Show API key"
                                ToolTip.delay: 450
                                background: null

                                contentItem: Item {
                                    Rectangle {
                                        anchors.fill: parent
                                        radius: 10
                                        color: revealKey.hovered
                                               ? Qt.rgba(0.25, 0.72, 0.92, 0.18) :
                                                 Qt.rgba(0.3, 0.4, 0.5, 0.08)
                                    }

                                    Canvas {
                                        id: visibilityIcon
                                        anchors.centerIn: parent
                                        width: 18
                                        height: 12

                                        onPaint: {
                                            var ctx = getContext("2d");
                                            ctx.reset();
                                            ctx.lineWidth = 1.45;
                                            ctx.lineCap = "round";
                                            ctx.lineJoin = "round";
                                            ctx.strokeStyle = root.cyan;

                                            ctx.beginPath();
                                            ctx.moveTo(1, 6);
                                            ctx.bezierCurveTo(4.1, 1.4, 13.9, 1.4, 17, 6);
                                            ctx.bezierCurveTo(13.9, 10.6, 4.1, 10.6, 1, 6);
                                            ctx.stroke();

                                            ctx.beginPath();
                                            ctx.arc(9, 6, 2.1, 0, Math.PI * 2);
                                            ctx.fillStyle = root.cyan;
                                            ctx.fill();

                                            if (!revealKey.checked) {
                                                ctx.beginPath();
                                                ctx.moveTo(2, 1);
                                                ctx.lineTo(16, 11);
                                                ctx.lineWidth = 1.7;
                                                ctx.strokeStyle = root.muted;
                                                ctx.stroke();
                                            }
                                        }
                                    }
                                }

                                onCheckedChanged: visibilityIcon.requestPaint()
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.preferredWidth: 300
                        Layout.fillWidth: true
                        spacing: 7
                        Text {
                            text: "TOOL-CAPABLE MODEL"
                            color: root.muted
                            font.pixelSize: 10
                            font.letterSpacing: 1.4
                            font.weight: Font.DemiBold
                        }
                        ComboBox {
                            id: modelCombo
                            Layout.fillWidth: true
                            implicitHeight: root.compactHeight ? 44 : 48
                            model: root.backend.models
                            editable: true
                            enabled: !root.backend.busy
                            leftPadding: 16

                            contentItem: Text {
                                leftPadding: 14
                                rightPadding: 36
                                text: modelCombo.editText.length > 0 ? modelCombo.editText :
                                                                       modelCombo.displayText
                                color: root.ink
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                                font.pixelSize: 13
                            }
                            indicator: ChevronIndicator {
                                implicitHeight: modelCombo.height
                                x: modelCombo.width - width
                                iconColor: modelCombo.enabled ? root.muted :
                                                                 Qt.rgba(0.56, 0.65, 0.75, 0.45)
                                expanded: modelCombo.popup.visible
                            }
                            background: Rectangle {
                                radius: 16
                                color: Qt.rgba(0.025, 0.055, 0.09, 0.82)
                                border.width: 1
                                border.color: modelCombo.activeFocus ? root.cyan : Qt.rgba(0.55,
                                                                                           0.74, 0.93,
                                                                                           0.18)
                            }
                        }
                    }

                    LiquidButton {
                        Layout.alignment: Qt.AlignBottom
                        Layout.preferredWidth: 90
                        Layout.preferredHeight: root.compactHeight ? 44 : 48
                        text: "Refresh"
                        iconText: "↻"
                        enabled: !root.backend.busy
                        onClicked: root.backend.loadModels(apiKey.text)
                    }
                    LiquidButton {
                        Layout.alignment: Qt.AlignBottom
                        Layout.preferredWidth: 82
                        Layout.preferredHeight: root.compactHeight ? 44 : 48
                        text: "Models"
                        onClicked: {
                            root.infoTitle = "Model orchestration";
                            root.infoText = root.backend.modelOrchestrationText;
                            infoDialog.open();
                        }
                    }
                    LiquidButton {
                        Layout.alignment: Qt.AlignBottom
                        Layout.preferredWidth: 108
                        Layout.preferredHeight: root.compactHeight ? 44 : 48
                        text: "Capabilities"
                        onClicked: {
                            root.infoTitle = "CST capability browser";
                            root.infoText = root.backend.capabilityText;
                            infoDialog.open();
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 0
                spacing: root.sectionGap

                GlassPanel {
                    Layout.preferredWidth: root.compactWidth ? 420 : 460
                    Layout.minimumWidth: root.compactWidth ? 370 : 410
                    Layout.fillHeight: true
                    edgeColor: Qt.rgba(0.33, 0.80, 0.98, 0.24)

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: root.compactHeight ? 16 : 22
                        spacing: root.compactHeight ? 9 : 14

                        RowLayout {
                            Layout.fillWidth: true
                            ColumnLayout {
                                spacing: 2
                                Text {
                                    text: "Design composer"
                                    color: root.ink
                                    font.pixelSize: 19
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    text: "Structured intent, natural language"
                                    color: root.muted
                                    font.pixelSize: 11
                                }
                            }
                            Item {
                                Layout.fillWidth: true
                            }
                            Rectangle {
                                Layout.preferredWidth: 38
                                Layout.preferredHeight: 38
                                radius: 13
                                color: Qt.rgba(0.2, 0.67, 0.9, 0.14)
                                Text {
                                    anchors.centerIn: parent
                                    text: "⌁"
                                    color: root.cyan
                                    font.pixelSize: 22
                                }
                            }
                        }

                        Text {
                            text: "ANTENNA FAMILY"
                            color: root.muted
                            font.pixelSize: 10
                            font.letterSpacing: 1.4
                            font.weight: Font.DemiBold
                        }

                        ComboBox {
                            id: familyCombo
                            Layout.fillWidth: true
                            implicitHeight: root.compactHeight ? 44 : 50
                            model: root.backend.familyOptions
                            textRole: "display"
                            valueRole: "id"
                            enabled: !root.backend.busy
                            leftPadding: 16

                            contentItem: Text {
                                leftPadding: 14
                                rightPadding: 36
                                text: familyCombo.displayText
                                color: root.ink
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                                font.pixelSize: 13
                                font.weight: Font.Medium
                            }
                            indicator: ChevronIndicator {
                                implicitHeight: familyCombo.height
                                x: familyCombo.width - width
                                iconColor: familyCombo.enabled ? root.muted :
                                                                  Qt.rgba(0.56, 0.65, 0.75, 0.45)
                                expanded: familyCombo.popup.visible
                            }
                            background: Rectangle {
                                radius: 17
                                color: Qt.rgba(0.025, 0.055, 0.09, 0.82)
                                border.width: 1
                                border.color: familyCombo.activeFocus ? root.cyan : Qt.rgba(0.55,
                                                                                            0.74, 0.93,
                                                                                            0.18)
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: familyCombo.currentIndex >= 0
                                  ? root.backend.familyOptions[familyCombo.currentIndex].description :
                                    ""
                            color: "#9CB5CB"
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                text: "REQUIREMENTS"
                                color: root.muted
                                font.pixelSize: 10
                                font.letterSpacing: 1.4
                                font.weight: Font.DemiBold
                            }
                            Item {
                                Layout.fillWidth: true
                            }
                            LiquidButton {
                                implicitWidth: 118
                                implicitHeight: 38
                                text: "Use example"
                                iconText: "✦"
                                onClicked: {
                                    promptArea.text = root.backend.familyExample(
                                        familyCombo.currentValue);
                                }
                            }
                        }

                        TextArea {
                            id: promptArea
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.minimumHeight: root.compactHeight ? 108 : 210
                            color: root.ink
                            placeholderText:
                            "Describe frequency, geometry, material, feed, sweep and monitors…"
                            placeholderTextColor: "#60758C"
                            wrapMode: TextEdit.Wrap
                            selectByMouse: true
                            font.pixelSize: 13
                            leftPadding: 16
                            rightPadding: 16
                            topPadding: 15
                            bottomPadding: 15

                            background: Rectangle {
                                radius: 20
                                color: Qt.rgba(0.018, 0.045, 0.075, 0.88)
                                border.width: 1
                                border.color: promptArea.activeFocus ? root.cyan : Qt.rgba(0.55,
                                                                                           0.74, 0.93,
                                                                                           0.18)
                                Behavior on border.color {
                                    ColorAnimation {
                                        duration: 160
                                    }
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: root.compactHeight ? 42 : 48
                            radius: 16
                            color: Qt.rgba(0.05, 0.16, 0.21, 0.64)
                            border.width: 1
                            border.color: Qt.rgba(0.34, 0.82, 0.78, 0.16)
                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 12
                                spacing: 9
                                Text {
                                    text: "✓"
                                    color: "#6EE7B7"
                                    font.pixelSize: 14
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: "Preview is read-only. Every CST write requires approval."
                                    color: "#A8C9CA"
                                    font.pixelSize: 10
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            LiquidButton {
                                Layout.fillWidth: true
                                Layout.preferredHeight: root.compactHeight ? 46 : 52
                                text: "Preview design"
                                iconText: "◌"
                                variant: "primary"
                                enabled: !root.backend.busy
                                onClicked: {
                                    root.activeReviewTab = 1;
                                    root.backend.runAgent(apiKey.text, modelCombo.currentText,
                                                          familyCombo.currentValue, promptArea.text,
                                                          "preview");
                                }
                            }
                            LiquidButton {
                                Layout.fillWidth: true
                                Layout.preferredHeight: root.compactHeight ? 46 : 52
                                text: "Build in CST"
                                iconText: "◇"
                                variant: "build"
                                enabled: !root.backend.busy
                                onClicked: {
                                    root.activeReviewTab = 1;
                                    root.backend.runAgent(apiKey.text, modelCombo.currentText,
                                                          familyCombo.currentValue, promptArea.text,
                                                          "build");
                                }
                            }
                        }
                    }
                }

                GlassPanel {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumWidth: root.compactWidth ? 420 : 470
                    edgeColor: Qt.rgba(0.58, 0.48, 0.98, 0.22)

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: root.compactHeight ? 16 : 22
                        spacing: root.compactHeight ? 10 : 14

                        RowLayout {
                            Layout.fillWidth: true
                            ColumnLayout {
                                spacing: 2
                                Text {
                                    text: "Design review"
                                    color: root.ink
                                    font.pixelSize: 19
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    text: "Readable output and traceable tool activity"
                                    color: root.muted
                                    font.pixelSize: 11
                                }
                            }
                            Item {
                                Layout.fillWidth: true
                            }
                            LiquidButton {
                                implicitWidth: 88
                                implicitHeight: 38
                                text: "Copy"
                                onClicked: root.backend.copyText(root.activeReviewTab === 0
                                                                 ? root.backend.assistantText :
                                                                   root.backend.activityText)
                            }
                            LiquidButton {
                                implicitWidth: 88
                                implicitHeight: 38
                                text: "Clear"
                                onClicked: root.backend.clearResults()
                            }
                        }

                        Rectangle {
                            id: tabRail
                            Layout.preferredWidth: 250
                            implicitHeight: 42
                            radius: 15
                            color: Qt.rgba(0.02, 0.05, 0.085, 0.72)
                            border.width: 1
                            border.color: Qt.rgba(0.6, 0.78, 0.95, 0.12)

                            Rectangle {
                                width: (parent.width - 8) / 2
                                height: parent.height - 8
                                y: 4
                                x: root.activeReviewTab === 0 ? 4 : parent.width / 2
                                radius: 12
                                color: Qt.rgba(0.15, 0.55, 0.78, 0.24)
                                border.width: 1
                                border.color: Qt.rgba(0.35, 0.82, 1.0, 0.25)
                                Behavior on x {
                                    NumberAnimation {
                                        duration: 220
                                        easing.type: Easing.OutCubic
                                    }
                                }
                            }

                            Row {
                                anchors.fill: parent
                                anchors.margins: 4
                                Repeater {
                                    model: ["Assistant", "Activity"]
                                    Item {
                                        id: reviewTab
                                        required property int index
                                        required property string modelData
                                        width: (tabRail.width - 8) / 2
                                        height: tabRail.height - 8
                                        Text {
                                            anchors.centerIn: parent
                                            text: reviewTab.modelData
                                            color: reviewTab.index === root.activeReviewTab
                                                   ? root.cyan : root.muted
                                            font.pixelSize: 12
                                            font.weight: Font.DemiBold
                                        }
                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: root.activeReviewTab = reviewTab.index
                                        }
                                    }
                                }
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: "Requirements  Â·  Calculations  Â·  Structure  Â·  Simulation  Â·  Validation  Â·  CST operations  Â·  Model activity  Â·  Execution activity  Â·  Results"
                            color: "#6F8DA8"
                            font.pixelSize: 9
                            wrapMode: Text.WordWrap
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            radius: 21
                            color: Qt.rgba(0.012, 0.035, 0.062, 0.84)
                            border.width: 1
                            border.color: Qt.rgba(0.48, 0.76, 0.96, 0.16)
                            clip: true

                            ScrollView {
                                anchors.fill: parent
                                anchors.margins: 18
                                visible: root.activeReviewTab === 0
                                opacity: visible ? 1 : 0

                                TextEdit {
                                    width: parent.width
                                    readOnly: true
                                    selectByMouse: true
                                    text: root.backend.assistantText
                                    textFormat: Text.MarkdownText
                                    wrapMode: TextEdit.Wrap
                                    color: "#DDEBFA"
                                    selectionColor: "#17648D"
                                    font.pixelSize: 13
                                }
                            }

                            Text {
                                anchors.centerIn: parent
                                visible: root.activeReviewTab === 0
                                         && root.backend.assistantText.length === 0 &&
                                         !root.backend.busy
                                width: parent.width - 80
                                horizontalAlignment: Text.AlignHCenter
                                text: "Your calculated design brief will appear here.\nPreview first, then build."
                                color: "#5F7489"
                                font.pixelSize: 13
                                lineHeight: 1.35
                            }

                            ScrollView {
                                anchors.fill: parent
                                anchors.margins: 18
                                visible: root.activeReviewTab === 1
                                opacity: visible ? 1 : 0

                                TextArea {
                                    width: parent.width
                                    readOnly: true
                                    selectByMouse: true
                                    text: root.backend.activityText
                                    color: "#9FC3D9"
                                    wrapMode: TextEdit.Wrap
                                    font.family: "Cascadia Mono"
                                    font.pixelSize: 11
                                    background: null
                                }
                            }

                            Item {
                                anchors.centerIn: parent
                                visible: root.backend.busy
                                width: 160
                                height: 86

                                Rectangle {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: 34
                                    height: 34
                                    radius: 17
                                    color: "transparent"
                                    border.width: 3
                                    border.color: Qt.rgba(0.35, 0.82, 1.0, 0.25)

                                    Rectangle {
                                        width: 8
                                        height: 8
                                        radius: 4
                                        color: root.cyan
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        y: -1
                                    }

                                    RotationAnimation on rotation {
                                        running: root.backend.busy
                                        loops: Animation.Infinite
                                        from: 0
                                        to: 360
                                        duration: 900
                                    }
                                }
                                Text {
                                    anchors.bottom: parent.bottom
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: root.backend.status
                                    color: root.muted
                                    font.pixelSize: 11
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Dialog {
        id: approvalDialog
        modal: true
        anchors.centerIn: parent
        width: Math.min(root.width - 120, 860)
        height: Math.min(root.height - 100, 700)
        padding: 0
        closePolicy: Popup.NoAutoClose

        background: GlassPanel {
            cornerRadius: 30
            glassColor: Qt.rgba(0.035, 0.065, 0.105, 0.98)
            edgeColor: Qt.rgba(0.96, 0.72, 0.38, 0.30)
        }

        contentItem: ColumnLayout {
            spacing: 16

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 92
                radius: 26
                color: Qt.rgba(0.22, 0.13, 0.05, 0.58)
                border.width: 1
                border.color: Qt.rgba(1.0, 0.72, 0.36, 0.22)
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 14
                    Rectangle {
                        Layout.preferredWidth: 46
                        Layout.preferredHeight: 46
                        radius: 16
                        color: Qt.rgba(1.0, 0.64, 0.24, 0.18)
                        Text {
                            anchors.centerIn: parent
                            text: "!"
                            color: root.amber
                            font.pixelSize: 22
                            font.bold: true
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        Text {
                            text: "Review CST write"
                            color: root.ink
                            font.pixelSize: 20
                            font.weight: Font.DemiBold
                        }
                        Text {
                            text: root.approvalTool
                            color: root.amber
                            font.pixelSize: 12
                        }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                text: "Approval controls CST and saves a project. The solver remains locked. Verify every value before continuing."
                color: "#B5C7D9"
                wrapMode: Text.WordWrap
                font.pixelSize: 12
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 20
                color: Qt.rgba(0.012, 0.032, 0.055, 0.9)
                border.width: 1
                border.color: Qt.rgba(0.58, 0.75, 0.92, 0.15)

                ScrollView {
                    anchors.fill: parent
                    anchors.margins: 14
                    TextArea {
                        width: parent.width
                        readOnly: true
                        selectByMouse: true
                        text: "ARGUMENTS\n" + root.approvalArguments + "\n\nPREVIEW\n"
                              + root.approvalPreview
                        color: "#BBD0E4"
                        wrapMode: TextEdit.Wrap
                        font.family: "Cascadia Mono"
                        font.pixelSize: 10
                        background: null
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                Item {
                    Layout.fillWidth: true
                }
                LiquidButton {
                    text: "Deny build"
                    implicitWidth: 140
                    onClicked: {
                        approvalDialog.close();
                        root.backend.resolveApproval(false);
                    }
                }
                LiquidButton {
                    text: "Approve CST build"
                    iconText: "✓"
                    variant: "build"
                    implicitWidth: 190
                    onClicked: {
                        approvalDialog.close();
                        root.backend.resolveApproval(true);
                    }
                }
            }
        }
    }

    Dialog {
        id: infoDialog
        modal: true
        anchors.centerIn: parent
        width: Math.min(root.width - 120, 980)
        height: Math.min(root.height - 100, 720)
        padding: 0

        background: GlassPanel {
            cornerRadius: 30
            glassColor: Qt.rgba(0.035, 0.065, 0.105, 0.98)
            edgeColor: Qt.rgba(0.34, 0.82, 1.0, 0.30)
        }

        contentItem: ColumnLayout {
            spacing: 14
            Text {
                text: root.infoTitle
                color: root.ink
                font.pixelSize: 21
                font.weight: Font.DemiBold
            }
            Text {
                visible: root.infoTitle === "Model orchestration"
                text: "Keys remain in process memory. Role assignments contain model IDs only."
                color: root.muted
                font.pixelSize: 11
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 18
                color: Qt.rgba(0.012, 0.032, 0.055, 0.9)
                border.width: 1
                border.color: Qt.rgba(0.58, 0.75, 0.92, 0.15)
                ScrollView {
                    anchors.fill: parent
                    anchors.margins: 14
                    TextArea {
                        width: parent.width
                        readOnly: true
                        selectByMouse: true
                        text: root.infoText
                        color: "#BBD0E4"
                        wrapMode: TextEdit.Wrap
                        font.family: "Cascadia Mono"
                        font.pixelSize: 10
                        background: null
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                LiquidButton {
                    visible: root.infoTitle === "Model orchestration"
                    text: "Use selected model for all roles"
                    implicitWidth: 245
                    onClicked: {
                        root.backend.useModelForAllRoles(modelCombo.currentText);
                        root.infoText = root.backend.modelOrchestrationText;
                    }
                }
                Item { Layout.fillWidth: true }
                LiquidButton {
                    text: "Close"
                    implicitWidth: 100
                    onClicked: infoDialog.close()
                }
            }
        }
    }

    Rectangle {
        id: toast
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 24
        width: Math.min(toastText.implicitWidth + 54, root.width - 120)
        height: 52
        radius: 18
        color: Qt.rgba(0.12, 0.05, 0.08, 0.96)
        border.width: 1
        border.color: Qt.rgba(1.0, 0.38, 0.48, 0.36)
        opacity: 0
        visible: opacity > 0

        Text {
            id: toastText
            anchors.centerIn: parent
            width: parent.width - 30
            text: ""
            color: "#FFD2D8"
            elide: Text.ElideRight
            horizontalAlignment: Text.AlignHCenter
            font.pixelSize: 12
        }

        Behavior on opacity {
            NumberAnimation {
                duration: 180
            }
        }
        Timer {
            id: toastTimer
            interval: 5200
            onTriggered: toast.opacity = 0
        }
    }

    Connections {
        target: root.backend

        function onApprovalRequested(toolName, argumentsJson, previewJson) {
            root.approvalTool = toolName;
            root.approvalArguments = argumentsJson;
            root.approvalPreview = previewJson;
            approvalDialog.open();
        }

        function onShowError(message) {
            toastText.text = message;
            toast.opacity = 1;
            toastTimer.restart();
        }

        function onAssistantTextChanged() {
            if (root.backend.assistantText.length > 0)
                root.activeReviewTab = 0;
        }
    }
}
