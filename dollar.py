"""
$1 Unistroke Recognizer.

A tiny, dependency-free gesture recogniser (Wobbrock, Wilson & Li, 2007).
Give it example strokes (templates) and it will tell you which one a new
stroke most resembles, invariant to scale and position -- and, optionally,
to rotation.  Perfect for matching wand "spells" with no machine learning
and no training data beyond a handful of examples.

A "stroke" is just a list of (x, y) points in the order they were drawn.
"""
import math

# A single 2-D sample point and an ordered sequence of them (a stroke).
Point = tuple[float, float]
Stroke = list[Point]

NUM_POINTS = 64                      # resample every stroke to this many points
SQUARE_SIZE = 250.0                  # normalise into this reference box
ANGLE_RANGE = math.radians(45.0)     # how far to search when de-rotating
ANGLE_PRECISION = math.radians(2.0)
PHI = 0.5 * (-1.0 + math.sqrt(5.0))  # golden ratio, for the angle search
HALF_DIAGONAL = 0.5 * math.sqrt(2.0 * SQUARE_SIZE * SQUARE_SIZE)


def _distance(p1: Point, p2: Point) -> float:
    """
    Euclidean distance between two points.

    Parameters:
        - p1: The first point.
        - p2: The second point.

    Returns:
        - The straight-line distance from p1 to p2.
    """
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def _path_length(points: Stroke) -> float:
    """
    Total length of the polyline through the stroke points.

    Parameters:
        - points: Ordered stroke points.

    Returns:
        - The summed segment lengths along the stroke.
    """
    return sum(_distance(points[i - 1], points[i]) for i in range(1, len(points)))


def _resample(points: Stroke, n: int = NUM_POINTS) -> Stroke:
    """
    Resample a stroke to n points spaced at equal arc length.

    Parameters:
        - points: The raw stroke, which may have unevenly spaced points.
        - n: The number of points to produce (default NUM_POINTS).

    Returns:
        - Exactly n points evenly distributed along the original path.
    """
    points = list(points)
    interval = _path_length(points) / (n - 1)
    if interval == 0:
        return [points[0]] * n
    accumulated = 0.0
    new_points: Stroke = [points[0]]
    i = 1
    while i < len(points):
        d = _distance(points[i - 1], points[i])
        if accumulated + d >= interval:
            t = (interval - accumulated) / d
            qx = points[i - 1][0] + t * (points[i][0] - points[i - 1][0])
            qy = points[i - 1][1] + t * (points[i][1] - points[i - 1][1])
            q = (qx, qy)
            new_points.append(q)
            points.insert(i, q)   # consider q as the next anchor
            accumulated = 0.0
        else:
            accumulated += d
        i += 1
    # floating point can leave us one short
    while len(new_points) < n:
        new_points.append(points[-1])
    return new_points[:n]


def _centroid(points: Stroke) -> Point:
    """
    Mean (x, y) of the stroke points.

    Parameters:
        - points: The stroke to average.

    Returns:
        - The centroid of the stroke.
    """
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    return cx, cy


def _indicative_angle(points: Stroke) -> float:
    """
    Angle from the centroid to the first point of the stroke.

    Parameters:
        - points: The stroke to measure.

    Returns:
        - The indicative angle in radians, used to de-rotate the stroke.
    """
    cx, cy = _centroid(points)
    return math.atan2(cy - points[0][1], cx - points[0][0])


def _rotate_by(points: Stroke, theta: float) -> Stroke:
    """
    Rotate a stroke about its centroid by theta radians.

    Parameters:
        - points: The stroke to rotate.
        - theta: The rotation angle in radians.

    Returns:
        - The rotated stroke.
    """
    cx, cy = _centroid(points)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    out: Stroke = []
    for x, y in points:
        dx, dy = x - cx, y - cy
        out.append((dx * cos_t - dy * sin_t + cx, dx * sin_t + dy * cos_t + cy))
    return out


def _bounding_box(points: Stroke) -> tuple[float, float, float, float]:
    """
    Axis-aligned bounding box of the stroke.

    Parameters:
        - points: The stroke to bound.

    Returns:
        - (min_x, min_y, width, height).
    """
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def _scale_to_square(points: Stroke, size: float = SQUARE_SIZE) -> Stroke:
    """
    Non-uniformly scale a stroke to fit a size x size box.

    Parameters:
        - points: The stroke to scale.
        - size: The side length of the target square (default SQUARE_SIZE).

    Returns:
        - The scaled stroke.
    """
    _, _, w, h = _bounding_box(points)
    out: Stroke = []
    for x, y in points:
        sx = x * (size / w) if w else x
        sy = y * (size / h) if h else y
        out.append((sx, sy))
    return out


def _translate_to_origin(points: Stroke) -> Stroke:
    """
    Translate a stroke so its centroid sits at the origin.

    Parameters:
        - points: The stroke to translate.

    Returns:
        - The translated stroke.
    """
    cx, cy = _centroid(points)
    return [(x - cx, y - cy) for x, y in points]


def normalize(points: Stroke, rotation_tolerant: bool = True) -> Stroke:
    """
    Resample/scale/translate a raw stroke into a comparable canonical form.

    Parameters:
        - points: The raw stroke to canonicalise.
        - rotation_tolerant: If True, de-rotate by the indicative angle so
          matching is rotation invariant (default True).

    Returns:
        - The canonical-form stroke, ready for comparison.
    """
    points = _resample(points, NUM_POINTS)
    if rotation_tolerant:
        points = _rotate_by(points, -_indicative_angle(points))
    points = _scale_to_square(points, SQUARE_SIZE)
    points = _translate_to_origin(points)
    return points


def _path_distance(a: Stroke, b: Stroke) -> float:
    """
    Mean point-to-point distance between two equal-length strokes.

    Parameters:
        - a: The first stroke.
        - b: The second stroke, the same length as a.

    Returns:
        - The average distance between corresponding points.
    """
    return sum(_distance(a[i], b[i]) for i in range(len(a))) / len(a)


def _distance_at_angle(points: Stroke, template: Stroke, theta: float) -> float:
    """
    Path distance after rotating the candidate stroke by theta.

    Parameters:
        - points: The candidate stroke.
        - template: The template stroke to compare against.
        - theta: The trial rotation angle in radians.

    Returns:
        - The path distance at the given angle.
    """
    return _path_distance(_rotate_by(points, theta), template)


def _distance_at_best_angle(points: Stroke, template: Stroke) -> float:
    """
    Minimum path distance over a golden-section search of rotations.

    Parameters:
        - points: The candidate stroke.
        - template: The template stroke to compare against.

    Returns:
        - The smallest path distance found within +/-ANGLE_RANGE.
    """
    a, b = -ANGLE_RANGE, ANGLE_RANGE
    x1 = PHI * a + (1 - PHI) * b
    f1 = _distance_at_angle(points, template, x1)
    x2 = (1 - PHI) * a + PHI * b
    f2 = _distance_at_angle(points, template, x2)
    while abs(b - a) > ANGLE_PRECISION:
        if f1 < f2:
            b, x2, f2 = x2, x1, f1
            x1 = PHI * a + (1 - PHI) * b
            f1 = _distance_at_angle(points, template, x1)
        else:
            a, x1, f1 = x1, x2, f2
            x2 = (1 - PHI) * a + PHI * b
            f2 = _distance_at_angle(points, template, x2)
    return min(f1, f2)


class Template:
    """
    A named reference stroke stored in canonical form.

    Parameters:
        - name: The label returned when this template is the best match.
        - raw_points: The example stroke for this gesture.
        - rotation_tolerant: Whether to normalise rotation invariantly
          (default True).
    """

    def __init__(self, name: str, raw_points: Stroke,
                 rotation_tolerant: bool = True) -> None:
        self.name = name
        self.raw_points = list(raw_points)
        self.points = normalize(raw_points, rotation_tolerant)


class Recognizer:
    """
    Holds templates and matches new strokes against them.

    Parameters:
        - rotation_tolerant: Whether matching should be rotation invariant
          (default True).
    """

    def __init__(self, rotation_tolerant: bool = True) -> None:
        self.rotation_tolerant = rotation_tolerant
        self.templates: list[Template] = []

    def add_template(self, name: str, raw_points: Stroke) -> None:
        """
        Add a named example stroke to the template set.

        Parameters:
            - name: The label for this gesture.
            - raw_points: The example stroke. Strokes with fewer than two
              points are ignored.
        """
        if len(raw_points) < 2:
            return
        self.templates.append(Template(name, raw_points, self.rotation_tolerant))

    def recognize(self, raw_points: Stroke) -> tuple[str | None, float]:
        """
        Return (name, score) for the best matching template.

        Parameters:
            - raw_points: The stroke to classify.

        Returns:
            - (name, score) of the best match; score in [0, 1] where 1.0 is a
              perfect match. (None, 0.0) if there are no templates or the
              stroke is degenerate.
        """
        if not self.templates or len(raw_points) < 2:
            return None, 0.0
        candidate = normalize(raw_points, self.rotation_tolerant)
        best_name, best_distance = None, float("inf")
        for tmpl in self.templates:
            if self.rotation_tolerant:
                d = _distance_at_best_angle(candidate, tmpl.points)
            else:
                d = _path_distance(candidate, tmpl.points)
            if d < best_distance:
                best_distance, best_name = d, tmpl.name
        score = 1.0 - best_distance / HALF_DIAGONAL
        return best_name, max(0.0, score)
