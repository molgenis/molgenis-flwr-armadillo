"""Tests for load_data."""

from unittest.mock import patch

import pytest

import molgenis_flwr_armadillo.data as data_mod
from molgenis_flwr_armadillo.data import load_data


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Point DATA_DIR at tmp_path and set the container name Armadillo would inject."""
    monkeypatch.setattr(data_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(data_mod, "CONTAINER_NAME", "flower-client-1")
    return tmp_path


@patch("molgenis_flwr_armadillo._http.requests.request")
def test_posts_to_armadillo(mock_request, data_dir):
    (data_dir / "myproject_train.parquet").write_bytes(b"test data")

    load_data("https://armadillo.example.com", "my-token", "myproject", "train.parquet")

    mock_request.assert_called_once_with(
        "POST",
        "https://armadillo.example.com/flower/push-data",
        headers={"Authorization": "Bearer my-token"},
        timeout=300,
        json={"project": "myproject", "resource": "train.parquet", "containerName": "flower-client-1"},
    )


@patch("molgenis_flwr_armadillo._http.requests.request")
def test_reads_and_deletes_file(mock_request, data_dir):
    filepath = data_dir / "proj_data%2Ftrain"
    filepath.write_bytes(b"raw file content")

    assert load_data("http://localhost:8080", "token", "proj", "data/train") == b"raw file content"
    assert not filepath.exists()


@patch("molgenis_flwr_armadillo._http.requests.request")
def test_slash_and_underscore_resources_do_not_collide(mock_request, data_dir):
    (data_dir / "proj_data%2Ftrain").write_bytes(b"slash content")
    (data_dir / "proj_data_train").write_bytes(b"underscore content")

    assert load_data("http://localhost:8080", "token", "proj", "data/train") == b"slash content"
    assert load_data("http://localhost:8080", "token", "proj", "data_train") == b"underscore content"


@patch("molgenis_flwr_armadillo._http.requests.request")
def test_raises_when_file_not_written(mock_request, data_dir):
    with pytest.raises(RuntimeError, match="was not written"):
        load_data("http://localhost:8080", "token", "proj", "file")


def test_raises_when_container_name_not_set(data_dir, monkeypatch):
    monkeypatch.setattr(data_mod, "CONTAINER_NAME", "")

    with pytest.raises(RuntimeError, match="ARMADILLO_CONTAINER_NAME"):
        load_data("http://localhost:8080", "token", "proj", "file")
