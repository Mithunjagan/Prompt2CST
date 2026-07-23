import QtQuick
import QtQuick.Controls

Control {
    id: control

    property string text: ""
    property string variant: "quiet"
    property string iconText: ""
    signal clicked

    implicitHeight: 48
    implicitWidth: 150
    hoverEnabled: true
    scale: pressArea.pressed ? 0.985 : (pressArea.containsMouse ? 1.012 : 1.0)
    opacity: enabled ? 1.0 : 0.42

    Behavior on scale {
        NumberAnimation {
            duration: 120
            easing.type: Easing.OutCubic
        }
    }
    Behavior on opacity {
        NumberAnimation {
            duration: 160
        }
    }

    contentItem: Item {
        Row {
            anchors.centerIn: parent
            spacing: 8

            Text {
                visible: control.iconText.length > 0
                text: control.iconText
                color: "#F5FBFF"
                font.pixelSize: 16
                font.weight: Font.DemiBold
            }
            Text {
                text: control.text
                color: control.variant === "quiet" ? "#C8D7E8" : "#F8FCFF"
                font.pixelSize: 13
                font.weight: Font.DemiBold
            }
        }
    }

    background: Rectangle {
        radius: 17
        border.width: 1
        border.color: {
            if (control.variant === "primary")
                return Qt.rgba(0.33, 0.85, 1.0, 0.58);
            if (control.variant === "build")
                return Qt.rgba(0.46, 0.98, 0.79, 0.52);
            return Qt.rgba(0.65, 0.78, 0.92, 0.20);
        }
        gradient: Gradient {
            GradientStop {
                position: 0
                color: {
                    if (control.variant === "primary")
                        return pressArea.containsMouse ? "#1699D0" : "#087DAF";
                    if (control.variant === "build")
                        return pressArea.containsMouse ? "#168E80" : "#0D716A";
                    return pressArea.containsMouse ? "#1C2B3D" : "#142132";
                }
            }
            GradientStop {
                position: 1
                color: {
                    if (control.variant === "primary")
                        return "#1859A5";
                    if (control.variant === "build")
                        return "#13595A";
                    return "#101A29";
                }
            }
        }
        Behavior on border.color {
            ColorAnimation {
                duration: 160
            }
        }
    }

    MouseArea {
        id: pressArea
        anchors.fill: parent
        enabled: control.enabled
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: control.clicked()
    }
}
