"""
Turns what the model found into a 0-10 severity score.

Three ideas:
1. Each detection gets a score between 0 and 1:
       type weight x model confidence x size factor
   - type weight: potholes are the most dangerous, longitudinal cracks the least.
   - confidence: how sure the model is (0-1).
   - size factor: bigger damage (as a share of the photo) counts more.
2. A photo with several detections combines them like independent risks:
       photo score = 1 - (1 - s1) x (1 - s2) x ...
   So two medium potholes score higher than one, but the total never passes 1.
   Multiplied by 10 to get 0-10.
3. A hotspot starts from its worst photo and goes up as more DIFFERENT people
   report it. A hotspot with only one reporter is capped below "severe",
   so one blurry or mistaken photo can never create a severe hotspot.
"""
import math

CLASS_WEIGHTS = {
    "pothole": 1.0,
    "alligator_crack": 0.7,
    "transverse_crack": 0.45,
    "longitudinal_crack": 0.35,
    "other": 0.4,
}
PERSON_CONFIDENCE = 0.5      # a person's report (no AI confidence) counts like a 50%-sure detection
PERSON_SIZE_FACTOR = 0.7     # no box drawn, so assume medium size
FULL_SIZE_AREA = 0.05        # damage covering 5% of the photo or more gets the full size factor
SINGLE_REPORTER_CAP = 6.9    # below the "severe" line (7.0)


def detection_score(det: dict) -> float:
    if det.get("box"):
        x1, y1, x2, y2 = det["box"]                 # fractions of the image, 0-1
        area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        size_factor = 0.4 + 0.6 * min(1.0, area / FULL_SIZE_AREA)
    else:
        size_factor = PERSON_SIZE_FACTOR
    confidence = det.get("confidence")
    confidence = PERSON_CONFIDENCE if confidence is None else float(confidence)
    return CLASS_WEIGHTS.get(det["label"], 0.3) * confidence * size_factor


def report_severity(detections: list[dict]) -> float:
    remaining = 1.0
    for det in detections:
        remaining *= 1.0 - detection_score(det)
    return round(10.0 * (1.0 - remaining), 2)


def hotspot_severity(max_report_severity: float, reporter_count: int) -> float:
    reporters = max(1, int(reporter_count))
    score = max_report_severity + math.log2(reporters)   # 1 person +0, 2 people +1, 4 people +2 ...
    if reporters < 2:
        score = min(score, SINGLE_REPORTER_CAP)
    return round(min(10.0, score), 2)


def severity_level(score: float) -> str:
    if score >= 7:
        return "severe"
    if score >= 4:
        return "moderate"
    return "minor"
