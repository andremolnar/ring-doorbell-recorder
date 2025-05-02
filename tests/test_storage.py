import pytest
from src.storage import save_file_to_nas, organize_files

def test_save_file_to_nas(mocker):
    mock_nas_path = "/mock/nas/path"
    mock_file_data = b"mock image data"
    mock_file_name = "test_image.jpg"

    # Mock the actual file saving function
    mock_save = mocker.patch("src.storage.open", mocker.mock_open())
    
    save_file_to_nas(mock_file_data, mock_file_name, mock_nas_path)

    mock_save.assert_called_once_with(f"{mock_nas_path}/{mock_file_name}", "wb")
    mock_save().write.assert_called_once_with(mock_file_data)

def test_organize_files():
    files = ["image1.jpg", "video1.mp4", "image2.jpg"]
    organized = organize_files(files)

    assert len(organized['images']) == 2
    assert len(organized['videos']) == 1
    assert "image1.jpg" in organized['images']
    assert "video1.mp4" in organized['videos']