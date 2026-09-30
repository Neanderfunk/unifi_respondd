import logging

from unifi_respondd.unifi_client import ort_im_rahmen

RAHMEN = [50.3, 5.8, 52.6, 9.5]  # sued, west, nord, ost


def test_im_rahmen_bleibt():
    assert ort_im_rahmen((51.2506, 6.9746), RAHMEN) == (51.2506, 6.9746)


def test_vertauscht_wird_getauscht_und_protokolliert(caplog):
    with caplog.at_level(logging.WARNING):
        assert ort_im_rahmen((6.9746, 51.2506), RAHMEN, "AP-1") == (51.2506, 6.9746)
    assert "AP-1" in caplog.text


def test_beide_ausserhalb_bleibt():
    assert ort_im_rahmen((48.1, 11.5), RAHMEN) == (48.1, 11.5)


def test_beide_innerhalb_bleibt():
    # ein quadratischer Rahmen, in dem beide Lesarten liegen
    assert ort_im_rahmen((51.0, 52.0), [50.0, 50.0, 53.0, 53.0]) == (51.0, 52.0)


def test_ohne_rahmen_oder_ohne_ort_unveraendert():
    assert ort_im_rahmen((6.9746, 51.2506), []) == (6.9746, 51.2506)
    assert ort_im_rahmen((6.9746, 51.2506), [1, 2, 3]) == (6.9746, 51.2506)
    assert ort_im_rahmen(None, RAHMEN) is None
