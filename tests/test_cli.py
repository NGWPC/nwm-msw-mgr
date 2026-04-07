"""Tests for CLI argument parsing"""

import pytest
from unittest.mock import patch

from mswm.manager import main


class TestCLI:
    """Verify the CLI parses arguments and uses correct build functions"""

    @patch("mswm.manager.build_default")
    def test_build_default(self, mock_build):
        """build_default command dispatches to build_default()"""
        with patch("sys.argv", ["mswm", "build_default", "/path/to/config.conf"]):
            main()
        mock_build.assert_called_once_with("/path/to/config.conf", False, None, False, False, None)

    @patch("mswm.manager.build_default")
    def test_build_default_with_cold_start(self, mock_build):
        """build_default --use_cold_start sets cold start flag"""
        with patch("sys.argv", ["mswm", "build_default", "/path/to/config.conf", "--use_cold_start", "--save_state"]):
            main()
        mock_build.assert_called_once_with("/path/to/config.conf", True, None, True, False, None)

    @patch("mswm.manager.build_default")
    def test_build_default_fcst(self, mock_build):
        """build_default fcst with state load and checkpoint"""
        with patch("sys.argv", ["mswm", "build_default", "/path/to/config.conf", "--load_state_from", "/path/to/state/", "--use_checkpoint", 100]):
            main()
        mock_build.assert_called_once_with("/path/to/config.conf", False, '/path/to/state/', False, True, 100)

    @patch("mswm.manager.build_calib")
    def test_build_calib(self, mock_build):
        """build_calib command dispatches to build_calib()"""
        with patch("sys.argv", ["mswm", "build_calib", "/path/to/config.conf"]):
            main()
        mock_build.assert_called_once_with(input_path="/path/to/config.conf")

    @patch("mswm.manager.build_region")
    def test_build_region(self, mock_build):
        """build_region command dispatches to build_region()"""
        with patch("sys.argv", ["mswm", "build_region", "/path/to/config.conf"]):
            main()
        mock_build.assert_called_once_with("/path/to/config.conf", False, None, False, False, None)

    @patch("mswm.manager.build_region")
    def test_build_region_with_cold_state(self, mock_build):
        """build_region with cold start state save"""
        with patch("sys.argv", ["mswm", "build_region", "/path/to/config.conf", "--use_cold_start", "--save_state"]):
            main()
        mock_build.assert_called_once_with("/path/to/config.conf", True, None, True, False, None)

    @patch("mswm.manager.build_region")
    def test_build_region_fcst(self, mock_build):
        """build_region fcst with state load and checkpoint"""
        with patch("sys.argv", ["mswm", "build_region", "/path/to/config.conf", "--load_state_from", "/path/to/state/", "--use_checkpoint", 100]):
            main()
        mock_build.assert_called_once_with("/path/to/config.conf", False, '/path/to/state/', False, True, 100)

    @patch("mswm.manager.build_fcst")
    def test_build_fcst_with_cold_start(self, mock_build):
        """build_fcst --use_cold_start sets cold start flag, --save_state sets state saving flag"""
        with patch("sys.argv", ["mswm", "build_fcst", "/path/to/config.conf", "/path/valid_yaml", "run_1", "--use_cold_start", "--save_state"]):
            main()
        mock_build.assert_called_once_with(input_path='/path/to/config.conf', valid_yaml='/path/valid_yaml', fcst_run_name='run_1', use_cold_start=True, use_warm_start=False,
                                           use_hindcast=False, use_lagged_ens=False, hind_cycle=None, prev_hind_cycle=None, lagged_ens_mem=None, forcing_lag=None, load_state_from=None, save_state=True)

    @patch("mswm.manager.build_fcst")
    def test_build_fcst(self, mock_build):
        """build_fcst command dispatches to build_fcst(), with mock state load"""
        with patch("sys.argv", ["mswm", "build_fcst", "/path/to/config.conf", "/path/valid_yaml", "run_1", "--load_state_from", "/path/to/state/"]):
            main()
        mock_build.assert_called_once_with(input_path='/path/to/config.conf', valid_yaml='/path/valid_yaml', fcst_run_name='run_1', use_cold_start=False, use_warm_start=False,
                                           use_hindcast=False, use_lagged_ens=False, hind_cycle=None, prev_hind_cycle=None, lagged_ens_mem=None, forcing_lag=None, load_state_from='/path/to/state/', save_state=False)

    @patch("mswm.manager.build_fcst")
    def test_build_fcst_with_warm_start(self, mock_build):
        """build_fcst --use_warm_start sets warm start flag, --save_state sets state saving flag"""
        with patch("sys.argv", ["mswm", "build_fcst", "/path/to/config.conf", "/path/valid_yaml", "run_1", "--use_warm_start", "--save_state"]):
            main()
        mock_build.assert_called_once_with(input_path='/path/to/config.conf', valid_yaml='/path/valid_yaml', fcst_run_name='run_1', use_cold_start=False, use_warm_start=True, use_hindcast=False,
                                           use_lagged_ens=False, hind_cycle=None, prev_hind_cycle=None, lagged_ens_mem=None, forcing_lag=None, load_state_from=None, save_state=True)

    @patch("mswm.manager.build_fcst")
    def test_build_fcst_with_hindcast(self, mock_build):
        """build_fcst --use_hindcast sets hindcasting flag, with mock state load"""
        with patch("sys.argv", ["mswm", "build_fcst", "/path/to/config.conf", "/path/valid_yaml", "run_1", "--use_hindcast", "--hind_cycle", "3", "--prev_hind_cycle", "0", "--load_state_from", "/path/to/state/"]):
            main()
        mock_build.assert_called_once_with(input_path='/path/to/config.conf', valid_yaml='/path/valid_yaml', fcst_run_name='run_1', use_cold_start=False, use_warm_start=False, use_hindcast=True, use_lagged_ens=False,
                                           hind_cycle=3, prev_hind_cycle=0, lagged_ens_mem=None, forcing_lag=None, load_state_from='/path/to/state/', save_state=False)

    @patch("mswm.manager.build_fcst")
    def test_build_fcst_with_lagged_ens(self, mock_build):
        """build_fcst --use_lagged_ens sets lagged ensemble flag, with mock state load"""
        with patch("sys.argv", ["mswm", "build_fcst", "/path/to/config.conf", "/path/valid_yaml", "run_1", "--use_lagged_ens", "--lagged_ens_mem", "mem2", "--forcing_lag", "6", "--load_state_from", "/path/to/state/"]):
            main()
        mock_build.assert_called_once_with(input_path='/path/to/config.conf', valid_yaml='/path/valid_yaml', fcst_run_name='run_1', use_cold_start=False, use_warm_start=False, use_hindcast=False, use_lagged_ens=True,
                                           hind_cycle=None, prev_hind_cycle=None, lagged_ens_mem='mem2', forcing_lag=6, load_state_from='/path/to/state/', save_state=False)

    def test_no_subcommand(self):
        """Missing subcommand should cause system exit"""
        with patch("sys.argv", ["mswm"]):
            with pytest.raises(SystemExit):
                main()

    def test_invalid_subcommand(self):
        """Invalid subcommand should cause system exit"""
        with patch("sys.argv", ["mswm", "build_invalid"]):
            with pytest.raises(SystemExit):
                main()
