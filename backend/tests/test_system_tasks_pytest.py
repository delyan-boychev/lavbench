from task_modules import system as system_mod


class TestRunDockerPrune:
    def test_success_returns_status_dict(self, mocker):
        mock_client = mocker.MagicMock()
        mock_client.images.prune.return_value = {
            "SpaceReclaimed": 12345,
            "ImagesDeleted": [{}, {}],
        }
        mocker.patch("task_modules.docker_utils._get_client", return_value=mock_client)
        result = system_mod.run_docker_prune()
        assert result["status"] == "success"
        assert "12345 bytes" in result["output"]
        assert "2 images" in result["output"]

    def test_exception_returns_failed_status(self, mocker):
        mock_client = mocker.MagicMock()
        mock_client.images.prune.side_effect = Exception("daemon unreachable")
        mocker.patch("task_modules.docker_utils._get_client", return_value=mock_client)
        result = system_mod.run_docker_prune()
        assert result["status"] == "failed"
        assert "daemon unreachable" in result["error"]
