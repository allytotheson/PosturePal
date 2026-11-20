"""Illustrative skeletal context with a highlighted, baseline-relative spine."""

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QWidget

from .domain import spine_points


class SpineWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(340, 400)
        self.setAccessibleName(
            "Back silhouette with highlighted spine. Drag to rotate, scroll to zoom."
        )
        self.yaw, self.pitch, self.zoom = math.pi - 0.08, -0.04, 1.0
        self.upper, self.lower = 0.0, 0.0
        self.states = ("aligned", "aligned")
        self.drag = None

    def set_posture(self, frame):
        self.upper, self.lower = frame.upper_deg, frame.lower_deg
        self.states = frame.upper_state, frame.lower_state
        self.update()

    def set_view(self, name):
        self.yaw = {
            "3D view": math.pi - 0.08,
            "Side": -math.pi / 2,
            "Back": math.pi,
            "Front": 0,
        }[name]
        self.pitch, self.zoom = -0.04, 1.0
        self.update()

    def project(self, point):
        x, y, z = point
        y -= 1.45
        z -= 0.3
        x, z = (
            x * math.cos(self.yaw) - z * math.sin(self.yaw),
            x * math.sin(self.yaw) + z * math.cos(self.yaw),
        )
        y, z = (
            y * math.cos(self.pitch) - z * math.sin(self.pitch),
            y * math.sin(self.pitch) + z * math.cos(self.pitch),
        )
        scale = min(self.width() / 4.1, self.height() / 4.8) * self.zoom * 9 / (9 - z)
        return QPointF(self.width() / 2 + x * scale, self.height() / 2 - y * scale), z

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#f8f8f6"))
        points = spine_points(self.upper, self.lower)
        profile = [
            (0, 0.67),
            (0.12, 0.64),
            (0.32, 0.53),
            (0.55, 0.69),
            (0.75, 0.88),
            (0.84, 0.98),
            (0.9, 0.86),
            (0.95, 0.30),
            (1, 0.25),
        ]

        def width(t):
            for (ta, wa), (tb, wb) in zip(profile, profile[1:]):
                if ta <= t <= tb:
                    f = (t - ta) / (tb - ta)
                    f = f * f * (3 - 2 * f)
                    return wa + (wb - wa) * f
            return profile[-1][1]

        def basis(i):
            before = points[max(0, i - 1)]
            after = points[min(23, i + 1)]
            return math.atan2(after[2] - before[2], after[1] - before[1])

        def world(i, x, dy, z):
            c = points[i]
            a = basis(i)
            return (
                c[0] + x,
                c[1] + dy * math.cos(a) - z * math.sin(a),
                c[2] + dy * math.sin(a) + z * math.cos(a),
            )

        # Neutral torso provides shoulders, waist and neck as visual landmarks.
        rings = []
        for i in range(24):
            depth = 0.24 if i < 21 else 0.18
            rings.append(
                [
                    world(
                        i,
                        width(i / 23) * math.cos(j * math.tau / 40),
                        0,
                        depth * math.sin(j * math.tau / 40),
                    )
                    for j in range(40)
                ]
            )
        faces = []
        for a, b in zip(rings, rings[1:]):
            for j in range(40):
                vertices = [a[j], a[(j + 1) % 40], b[(j + 1) % 40], b[j]]
                projected = [self.project(v) for v in vertices]
                shade = 241 + int(4 * math.sin(j * math.tau / 40 + 0.6))
                faces.append(
                    (
                        sum(v[1] for v in projected) / 4,
                        QPolygonF([v[0] for v in projected]),
                        QColor(shade, shade + 2, min(255, shade + 4)),
                    )
                )
        p.setPen(Qt.PenStyle.NoPen)
        for _, poly, color in sorted(faces, key=lambda f: f[0]):
            p.setBrush(color)
            p.drawPolygon(poly)
        # Contextual bones use projected curves and a muted palette so the
        # spinal column remains the visual focus. This is illustrative anatomy.
        unit = min(self.width() / 4.1, self.height() / 4.8) * self.zoom

        def bone(vertices, thickness=0.035, color="#e5dfd0"):
            line = QPolygonF([self.project(v)[0] for v in vertices])
            pen = QPen(QColor("#d8d1c2"), max(1, unit * thickness + 1.4))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(line)
            pen.setColor(QColor(color))
            pen.setWidthF(max(1, unit * thickness))
            p.setPen(pen)
            p.drawPolyline(line)

        # Paired ribs wrap from the back around the thorax.
        for i in range(8, 20):
            t = (i - 8) / 11
            radius = 0.53 + 0.31 * math.sin(t * math.pi * 0.85)
            for side in (-1, 1):
                rib = []
                for j in range(25):
                    angle = j / 24 * math.pi * 0.93
                    rib.append(
                        world(
                            i,
                            side * (0.10 + radius * math.sin(angle)),
                            -0.14 * math.sin(angle) - 0.10 * (angle / math.pi),
                            -0.16 + 0.43 * (1 - math.cos(angle)),
                        )
                    )
                bone(rib, 0.032)

        # Broad pelvic wings and shoulder blades establish familiar landmarks.
        def plate(index, vertices, color):
            poly = QPolygonF([self.project(world(index, *v))[0] for v in vertices])
            p.setPen(QPen(QColor("#ded7c8"), 0.8))
            p.setBrush(QColor(color))
            path = QPainterPath()
            path.moveTo((poly[-1] + poly[0]) * 0.5)
            for j in range(len(poly)):
                path.quadTo(poly[j], (poly[j] + poly[(j + 1) % len(poly)]) * 0.5)
            path.closeSubpath()
            p.drawPath(path)

        for side in (-1, 1):
            plate(
                1,
                [
                    (side * 0.12, 0.16, -0.13),
                    (side * 0.35, 0.43, -0.08),
                    (side * 0.66, 0.39, -0.04),
                    (side * 0.77, 0.23, 0.02),
                    (side * 0.68, -0.12, 0.03),
                    (side * 0.52, -0.36, -0.04),
                    (side * 0.20, -0.36, -0.13),
                    (side * 0.28, -0.13, -0.15),
                ],
                "#e7e1d3",
            )
            plate(
                17,
                [
                    (side * 0.24, 0.28, -0.25),
                    (side * 0.76, 0.32, -0.20),
                    (side * 0.68, 0.12, -0.26),
                    (side * 0.49, -0.42, -0.24),
                    (side * 0.26, -0.12, -0.29),
                ],
                "#ede8de",
            )
            bone(
                [
                    world(19, side * x, y, z)
                    for x, y, z in [
                        (0.18, 0.15, -0.10),
                        (0.46, 0.20, -0.12),
                        (0.75, 0.12, -0.12),
                        (0.94, 0.02, -0.08),
                    ]
                ],
                0.055,
            )
            # Faint upper arms provide orientation without a whole-body avatar.
            bone(
                [
                    world(19, side * 0.96, -0.03, -0.04),
                    world(19, side * 1.03, -0.65, 0.01),
                    world(19, side * 1.07, -1.12, 0.08),
                ],
                0.075,
                "#efebe3",
            )
            bone(
                [
                    world(19, side * 1.07, -1.12, 0.08),
                    world(19, side * 1.13, -1.85, 0.15),
                ],
                0.045,
                "#efebe3",
            )
            bone(
                [
                    world(19, side * 1.12, -1.12, 0.10),
                    world(19, side * 1.21, -1.85, 0.15),
                ],
                0.035,
                "#efebe3",
            )

        centers = [
            self.project(world(i, 0, 0, -0.285 if i < 21 else -0.2))[0]
            for i in range(24)
        ]
        # Individual vertebral bodies, transverse processes and posterior tips.
        # Draw as a highlight overlay, keeping them legible during rotation.
        for i, c in enumerate(centers):
            before = centers[max(0, i - 1)]
            after = centers[min(23, i + 1)]
            angle = (
                math.degrees(math.atan2(after.y() - before.y(), after.x() - before.x()))
                + 90
            )
            p.save()
            p.translate(c)
            p.rotate(angle)
            size = max(4, unit * (0.115 if i < 11 else 0.095 if i < 20 else 0.07))
            alert = self.states[1 if i < 11 else 0] in ("pending", "cue", "above")
            gradient = QLinearGradient(-size, 0, size, 0)
            gradient.setColorAt(0, QColor("#bca776" if not alert else "#bc8a3e"))
            gradient.setColorAt(0.45, QColor("#f4ecd4" if not alert else "#ffe2a4"))
            gradient.setColorAt(1, QColor("#c6b68d" if not alert else "#c18e43"))
            p.setPen(QPen(QColor("#ac9b76" if not alert else "#a7782f"), 0.65))
            p.setBrush(gradient)
            body = QPainterPath()
            body.moveTo(-size * 0.68, -size * 0.45)
            body.cubicTo(
                -size * 0.95,
                -size * 0.66,
                size * 0.95,
                -size * 0.66,
                size * 0.68,
                -size * 0.45,
            )
            body.lineTo(size * 0.68, -size * 0.10)
            body.lineTo(size * 1.42, -size * 0.25)
            body.quadTo(size * 1.65, size * 0.10, size * 0.75, size * 0.22)
            body.quadTo(size * 0.64, size * 0.60, size * 0.23, size * 0.48)
            body.lineTo(0, size * 0.86)
            body.lineTo(-size * 0.23, size * 0.48)
            body.quadTo(-size * 0.64, size * 0.60, -size * 0.75, size * 0.22)
            body.quadTo(-size * 1.65, size * 0.10, -size * 1.42, -size * 0.25)
            body.lineTo(-size * 0.68, -size * 0.10)
            body.closeSubpath()
            p.drawPath(body)
            p.setPen(QPen(QColor("#fff7e5"), 0.8))
            p.drawLine(
                QPointF(-size * 0.4, -size * 0.29), QPointF(size * 0.4, -size * 0.29)
            )
            p.restore()
        # Sacrum tapers into the pelvis beneath the lumbar column.
        plate(
            0,
            [
                (-0.19, -0.01, -0.31),
                (0.19, -0.01, -0.31),
                (0.14, -0.25, -0.32),
                (0, -0.48, -0.32),
                (-0.14, -0.25, -0.32),
            ],
            "#d6c7a4",
        )
        p.setPen(QColor("#626973"))
        p.drawText(16, 25, "Spinal column")
        p.drawText(
            self.rect().adjusted(8, 0, -8, -14),
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
            "Drag to rotate · Scroll to zoom · Illustrative anatomy",
        )

    def mousePressEvent(self, event):
        self.drag = event.position()

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            delta = event.position() - self.drag
            self.yaw += delta.x() * 0.008
            self.pitch = max(-0.8, min(0.8, self.pitch + delta.y() * 0.005))
            self.drag = event.position()
            self.update()

    def mouseReleaseEvent(self, event):
        self.drag = None

    def wheelEvent(self, event):
        self.zoom = max(0.6, min(1.7, self.zoom + event.angleDelta().y() / 1200))
        self.update()
