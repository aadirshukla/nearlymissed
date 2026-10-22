"""Add your algorithm-specific tests here when implementing the detector."""

from conflict_detector import detect_conflicts


def test_empty_tracks_return_no_events():
    zone = [[0, 0], [100, 0], [100, 100], [0, 100]]
    config = {
        "ttc_threshold_seconds": 3.0,
        "max_distance_pixels": 120.0,
        "min_track_age_frames": 5,
    }
    assert detect_conflicts([], zone, config) == []

