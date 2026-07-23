import QtQuick

Item {
    id: indicator

    property color iconColor: "#8FA6BE"
    property bool expanded: false

    implicitWidth: 42
    implicitHeight: 44

    Canvas {
        id: chevron

        anchors.centerIn: parent
        width: 14
        height: 8
        rotation: indicator.expanded ? 180 : 0

        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            ctx.beginPath();
            ctx.moveTo(1.25, 1.5);
            ctx.lineTo(7, 6.5);
            ctx.lineTo(12.75, 1.5);
            ctx.lineWidth = 1.7;
            ctx.lineCap = "round";
            ctx.lineJoin = "round";
            ctx.strokeStyle = indicator.iconColor;
            ctx.stroke();
        }

        Behavior on rotation {
            NumberAnimation {
                duration: 160
                easing.type: Easing.OutCubic
            }
        }
    }

    onIconColorChanged: chevron.requestPaint()
}
