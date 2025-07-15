import unittest
from unittest.mock import patch, MagicMock
from flask import Flask
from app.utils import arr_client

class TestArrClient(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['RADARR_API_KEY'] = 'test_radarr_key'
        self.app.config['RADARR_URL'] = 'http://radarr.test'
        self.app.config['SONARR_API_KEY'] = 'test_sonarr_key'
        self.app.config['SONARR_URL'] = 'http://sonarr.test'
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_parse_media_name(self):
        test_cases = [
            ("Show.S01E01.mkv", {"type": "tv", "title": "Show", "season": 1, "episode": 1, "year": None, "raw_name": "Show.S01E01.mkv"}),
            ("Show Name - Season 1 Episode 1.mp4", {"type": "tv", "title": "Show Name -", "season": 1, "episode": 1, "year": None, "raw_name": "Show Name - Season 1 Episode 1.mp4"}),
            ("The.Office.S05E12.HDTV.x264-LOL", {"type": "tv", "title": "The Office", "season": 5, "episode": 12, "year": None, "raw_name": "The.Office.S05E12.HDTV.x264-LOL"}),
            ("Series.Title.S02E03.1080p.WEB-DL.mkv", {"type": "tv", "title": "Series Title", "season": 2, "episode": 3, "year": None, "raw_name": "Series.Title.S02E03.1080p.WEB-DL.mkv"}),
            ("My.Show.2023.S01E01.German.DL.1080p.BluRay.AVC-TINGS", {"type": "tv", "title": "My Show", "year": 2023, "season": 1, "episode": 1, "raw_name": "My.Show.2023.S01E01.German.DL.1080p.BluRay.AVC-TINGS"}),
            ("Show.Title.1x01.Episode.Name.avi", {"type": "tv", "title": "Show Title", "season": 1, "episode": 1, "year": None, "raw_name": "Show.Title.1x01.Episode.Name.avi"}),
            ("Dr.Who.2005.S02.E03.The.School.Reunion", {"type": "tv", "title": "Dr Who 2005", "season": 2, "episode": 3, "year": None, "raw_name": "Dr.Who.2005.S02.E03.The.School.Reunion"}),
            ("Movie Title (2023).mkv", {"type": "movie", "title": "Movie Title", "year": 2023, "season": None, "episode": None, "raw_name": "Movie Title (2023).mkv"}),
            ("Another.Movie.2022.1080p.BluRay.x265.mkv", {"type": "movie", "title": "Another Movie", "year": 2022, "season": None, "episode": None, "raw_name": "Another.Movie.2022.1080p.BluRay.x265.mkv"}),
            ("The.Great.Film.2021.UHD.BluRay.2160p.TrueHD.Atmos.7.1.HEVC-GROUP", {"type": "movie", "title": "The Great Film", "year": 2021, "season": None, "episode": None, "raw_name": "The.Great.Film.2021.UHD.BluRay.2160p.TrueHD.Atmos.7.1.HEVC-GROUP"}),
            ("Film.With.Dots.In.Name.(2020).mp4", {"type": "movie", "title": "Film With Dots In Name", "year": 2020, "season": None, "episode": None, "raw_name": "Film.With.Dots.In.Name.(2020).mp4"}),
            ("Movie [2019] 720p", {"type": "movie", "title": "Movie", "year": 2019, "season": None, "episode": None, "raw_name": "Movie [2019] 720p"}),
            ("Random.File.1080p.mkv", {"type": "unknown", "title": "Random File", "year": None, "season": None, "episode": None, "raw_name": "Random.File.1080p.mkv"}),
            ("Documentary.Film.No.Year.mp4", {"type": "unknown", "title": "Documentary Film No Year", "year": None, "season": None, "episode": None, "raw_name": "Documentary.Film.No.Year.mp4"}),
            ("S01E01.Orphan.Episode.Format.mkv", {"type": "unknown", "title": "S01E01 Orphan Episode Format", "year": None, "season": None, "episode": None, "raw_name": "S01E01.Orphan.Episode.Format.mkv"}),
            ("2023.Movie.Title.No.Brackets.mkv", {"type": "unknown", "title": "2023 Movie Title No Brackets", "year": None, "season": None, "episode": None, "raw_name": "2023.Movie.Title.No.Brackets.mkv"}),
            ("JustAFileName", {"type": "unknown", "title": "JustAFileName", "year": None, "season": None, "episode": None, "raw_name": "JustAFileName"}),
            ("S01E01", {"type": "unknown", "title": "S01E01", "year": None, "season": None, "episode": None, "raw_name": "S01E01"}),
            ("(2023) Only Year.mkv", {"type": "unknown", "title": "(2023) Only Year", "year": None, "season": None, "episode": None, "raw_name": "(2023) Only Year.mkv"}),
        ]
        for item_name, expected_output in test_cases:
            with self.subTest(item_name=item_name):
                result = arr_client.parse_media_name(item_name)
                self.assertEqual(result, expected_output)

    @patch('app.utils.arr_client._sonarr_api_request')
    def test_check_sonarr_episode_exists_success(self, mock_api_request):
        mock_api_request.side_effect = [
            ([{"id": 123, "title": "Test Series", "titleSlug": "test-series"}]),
            ([
                {"seriesId": 123, "seasonNumber": 1, "episodeNumber": 1, "hasFile": True, "episodeFileId": 10, "monitored": True},
                {"seriesId": 123, "seasonNumber": 1, "episodeNumber": 2, "hasFile": False, "episodeFileId": 0, "monitored": True}
            ])
        ]
        self.assertTrue(arr_client.check_sonarr_episode_exists("Test Series", 1, 1))

    @patch('app.utils.arr_client._radarr_api_request')
    def test_check_radarr_movie_exists_success(self, mock_api_request):
        mock_api_request.return_value = [
            {"title": "Test Movie", "year": 2021, "hasFile": True, "sizeOnDisk": 1000, "id": 1}
        ]
        self.assertTrue(arr_client.check_radarr_movie_exists("Test Movie", 2021))

    @patch('app.utils.arr_client._sonarr_api_request')
    def test_check_sonarr_episode_exists_no_file(self, mock_api_request):
        mock_api_request.side_effect = [
            ([{"id": 123, "title": "Test Series"}]),
            ([{"seriesId": 123, "seasonNumber": 1, "episodeNumber": 1, "hasFile": False, "episodeFileId": 0, "monitored": True}])
        ]
        self.assertFalse(arr_client.check_sonarr_episode_exists("Test Series", 1, 1))

    @patch('app.utils.arr_client._radarr_api_request')
    def test_check_radarr_movie_exists_no_file(self, mock_api_request):
        mock_api_request.return_value = [
            {"title": "Test Movie", "year": 2021, "hasFile": False, "sizeOnDisk": 0, "id": 1}
        ]
        self.assertFalse(arr_client.check_radarr_movie_exists("Test Movie", 2021))

if __name__ == '__main__':
    unittest.main()
