import QtQuick

Rectangle {
    id: panel

    property color glassColor: Qt.rgba(0.055, 0.09, 0.145, 0.84)
    property color edgeColor: Qt.rgba(0.52, 0.78, 0.96, 0.18)
    property real cornerRadius: 26

    radius: cornerRadius
    color: glassColor
    border.width: 1
    border.color: edgeColor
    antialiasing: true

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: Math.max(0, panel.radius - 1)
        opacity: 0.52
        gradient: Gradient {
            GradientStop {
                position: 0.0
                color: Qt.rgba(0.32, 0.66, 0.92, 0.10)
            }
            GradientStop {
                position: 0.42
                color: Qt.rgba(0.08, 0.13, 0.21, 0.03)
            }
            GradientStop {
                position: 1.0
                color: Qt.rgba(0.32, 0.16, 0.48, 0.08)
            }
        }
    }
}
