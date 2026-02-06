"""
This module contains Pydantic classes to validate input.config files for the MSWM

@author: Jeff Wade
"""

from pydantic import BaseModel, Field, field_validator, model_validator, AliasChoices
from pydantic_core.core_schema import ValidationInfo
from pathlib import Path
from typing import Optional, Literal, Union


class StrictBaseModel(BaseModel):
    """
    Custom pydantic BaseModel that checks for absent or empty strings for required variables
    """
    @model_validator(mode="before")
    # Raise errors when required variables are absent or empty strings
    def check_empty_fields(cls, values):
        for field, value in values.items():
            # Check if string variable is empty
            if isinstance(value, str) and not value.strip():
                raise ValueError(f"Field '{field}' cannot be an empty string")
            # Check if path variable is empty
            if isinstance(value, Path) and not str(value).strip():
                raise ValueError(f"Field '{field}' cannot be an empty Path")

        return values


class GeneralConfig(StrictBaseModel):
    """
    Input.config general section requirement
    """
    basin: str
    domain: str
    environment: Literal["test", "oe"] = 'test'
    run_type: Literal["default", "calibration", "regionalization"]
    models: Optional[str] = None
    formulation: Optional[str] = None
    main_dir: str
    start_period: Optional[str] = None
    end_period: Optional[str] = None
    output_precip: Optional[bool] = None
    output_swe: Optional[bool] = None
    output_sm: Optional[bool] = None
    sm_profile_depth: Optional[list[float] | str] = Field(default_factory=lambda: [0.1, 0.4, 1.0, 2.0])
    sm_frac_depth: Optional[float] = 0.4

    @field_validator("sm_profile_depth", mode="before")
    @classmethod
    def check_sm_profile_depth(cls, val, info: ValidationInfo):
        """Validate sm_profile_depth input.
        Must be a list of 4 monotonically increasing float values, with the last value equal to 2.0.
        If None, set to default values [0.1, 0.4, 1.0, 2.0].
        """
        if info.data.get("output_sm") is not True:
            return None

        if val is None:
            return [0.1, 0.4, 1.0, 2.0]
        if isinstance(val, str):
            val = [float(x) for x in val.split(",")]
        if not isinstance(val, list) or len(val) != 4:
            raise ValueError("sm_profile_depth must be a list of 4 values.")
        for v in val:
            if not isinstance(v, (float, int)):
                raise ValueError("sm_profile_depth must be a list of float values.")
        if not all(earlier < later for earlier, later in zip(val, val[1:])):
            raise ValueError("sm_profile_depth values must be monotonically increasing (since it is accumualtive).")
        if val[-1] != 2.0:
            msg = f"The last value of sm_profile_depth is {val[-1]}, but it must be 2.0 m."
            raise ValueError(msg)

        return val

    @field_validator("sm_frac_depth", mode="before")
    @classmethod
    def check_sm_frac_depth(cls, val, info: ValidationInfo):
        """Validate sm_frac_depth input.
        Must be a float value corresponding to one of the sm_profile_depth values.
        If None, set to default value (0.4).
        """
        if info.data.get("output_sm") is not True:
            return None

        if val is None:
            return 0.4
        if isinstance(val, str):
            val = float(val)
        if not isinstance(val, (float, int)):
            raise ValueError("sm_frac_depth must be a float value.")
        sm_profile_depth = info.data.get("sm_profile_depth", [0.1, 0.4, 1.0, 2.0])
        if val not in sm_profile_depth:
            raise ValueError("sm_frac_depth must correspond to one of the sm_profile_depth values.")

        return val

    # Check optional fields that depend on run_type
    @model_validator(mode="after")
    def check_required_fields(self):
        # Models required unless run_type is regionalization
        if self.run_type != "regionalization" and not self.models:
            raise ValueError("`models` must be specified for a default and calibration runs.")

        # Start_period and end_period required unless run_type is calibration or default
        if self.run_type == "regionalization" and (not self.start_period or not self.end_period):
            raise ValueError("`start_period` and `end_period` must be specified for regionalization runs.")

        return self


class ModulePropertiesConfig(StrictBaseModel):
    """
    Input.config module properties section requirement
    """
    cfe_aet_rootzone: Optional[Union[int, bool, str]] = Field(None, validation_alias=AliasChoices("cfe-s_aet_rootzone", "cfe-x_aet_rootzone", "cfe_aet_rootzone"))
    pet_method: Optional[int] = None

    # Normalize is_aet_rootzone values
    @field_validator('cfe_aet_rootzone')
    def norm_aet_rootzone(cls, val):
        if val is None:
            return None
        if val in ('1', 1, True, "true", "True"):
            return 1
        if val in ('0', 0, False, "false", "False"):
            return 0
        raise ValueError(f"Invalid value set for cfe.aet_rootzone: {val}")


class RegionConfig(StrictBaseModel):
    """
    Input.config regionalization section requirement
    """
    form_assign_file: Optional[str] = None
    cat_grp_file: Optional[str] = None


class CalibConfig(StrictBaseModel):
    """
    Input.config calibration section requirement
    """
    optimization_algorithm: Optional[Literal["dds", "pso", "gwo"]] = None
    swarm_size: Optional[int] = None
    c1: Optional[int] = None
    c2: Optional[int] = None
    w: Optional[float] = None
    objective_function: Optional[Literal["kge", "nse", "nnse", "nselog", "corr", "csi", "pod",
                                         "rmse", "mae", "rsr", "far", "pkbias", "pkte", "evbias",
                                         "pbias", "lseg_fdc", "hseg_fdc"]] = None
    start_iteration: Optional[int] = None
    number_iteration: Optional[int] = None
    restart: Optional[int] = None
    calib_output_vars: Optional[bool] = None
    valid_output_vars: Optional[bool] = None
    calib_start_period: str
    calib_end_period: str
    calib_eval_start_period: str
    calib_eval_end_period: str
    valid_start_period: str
    valid_end_period: str
    valid_eval_start_period: str
    valid_eval_end_period: str
    full_eval_start_period: str
    full_eval_end_period: str
    save_output_iter: Optional[int] = None
    save_plot_iter: Optional[int] = None
    save_plot_iter_freq: Optional[int] = None
    streamflow_threshold: Optional[float] = None
    station_name: Optional[str] = None
    ngen_cerf: bool
    calibration_run_id: Optional[int] = None
    auth_token: Optional[str] = None
    user_email: Optional[str] = None
    calib_parameter_file: Optional[str] = None

    # Normalize case of optimization_algorithm
    @field_validator("optimization_algorithm", mode="before")
    def case_alg(cls, value):
        if isinstance(value, str):
            return value.lower()
        return value

    # Check optional fields that depend on optimization_algoritm
    @model_validator(mode="after")
    def check_required_fields(self):

        # swarm_size required unless optimization_algorithm is DDS
        if self.optimization_algorithm is not None and self.optimization_algorithm != "dds" and not self.swarm_size:
            raise ValueError("`swarm_size` must be specified for a PSO or GWO calibration run.")

        # c1 required if optimization_algorithm is PSO
        if self.optimization_algorithm is not None and self.optimization_algorithm == "pso" and not self.c1:
            raise ValueError("`c1` must be specified for a PSO calibration run.")

        # c2 required if optimization_algorithm is PSO
        if self.optimization_algorithm is not None and self.optimization_algorithm == "pso" and not self.c2:
            raise ValueError("`c2` must be specified for a PSO calibration run.")

        # w required if optimization_algorithm is PSO
        if self.optimization_algorithm is not None and self.optimization_algorithm == "pso" and not self.w:
            raise ValueError("`w` must be specified for a PSO calibration run.")

        # restart must be 0 or 1
        if self.restart is not None and self.restart not in (0, 1):
            print(self.restart)
            raise ValueError("`restart` must be 0 or 1.")

        # save_output_iter must be 0 or 1
        if self.save_output_iter is not None and self.save_output_iter not in (0, 1):
            raise ValueError("`save_output_iter` must be 0 or 1.")

        # save_plot_iter must be 0 or 1
        if self.save_plot_iter is not None and self.save_plot_iter not in (0, 1):
            raise ValueError("`save_plot_iter` must be 0 or 1.")

        return self


valid_configs = ['standard_ana', 'aorc', 'extended_ana', 'long_range_mem1', 'long_range_mem2', 'long_range_mem3', 'long_range_mem4',
                 'medium_range_blend', 'medium_range', 'nwm', 'short_range', 'short_range_alaska', 'medium_range_blend_alaska', 'short_range_extended_alaska',
                 'short_range_hawaii', 'short_range_puertorico', 'extended_ana_alaska', 'standard_ana_alaska', 'standard_ana_hawaii',
                 'standard_ana_puertorico', ]


class ForcingConfig(StrictBaseModel):
    """
    Input.config Forcing section requirement
    """
    forcing_provider: Literal['csv', 'bmi']
    forcing_dir: Optional[str] = None
    forcing_template_dir: Optional[str] = None
    root_dir: Optional[str] = None
    forcing_configuration: Optional[str] = None
    cycle_datetime: Optional[str] = None
    cold_start_datetime: Optional[str] = None
    global_domain: Optional[str] = "CONUS"
    forcing_static_dir: Optional[str] = None

    # Check optional fields that depend on forcing_provider
    @model_validator(mode="after")
    def check_required_fields(self):

        # forcing_dir required if forcing_provider is csv
        if self.forcing_provider == 'csv' and self.forcing_dir is None:
            raise ValueError("`forcing_dir` must be specified for a run using csv forcing provider.")

        # forcing_configuration required if forcing_provider is csv
        if self.forcing_provider == 'bmi':
            if self.forcing_configuration is None:
                raise ValueError("`forcing_configuration` must be specified for a run using bmi forcing provider.")
            else:
                if self.forcing_configuration not in valid_configs:
                    raise ValueError(f"Invalid `forcing_configuration` value: '{self.forcing_configuration}'."
                                     f"Valid options are: {', '.join(valid_configs)}.")

        # forcing template dir required if forcing_provider is csv
        if self.forcing_provider == 'bmi' and self.forcing_template_dir is None:
            raise ValueError("`forcing_template_dir` must be specified for a run using bmi forcing provider.")

        # root dir required if forcing_provider is csv
        if self.forcing_provider == 'bmi' and self.root_dir is None:
            raise ValueError("`root_dir` must be specified for a run using bmi forcing provider.")

        # forcing_static_dir required if forcing_provider is bmi and forcing_configuration is nwm
        if self.forcing_provider == 'bmi' and self.forcing_configuration == 'nwm' and self.forcing_static_dir is None:
            raise ValueError("`forcing_static_dir` must be specified for a run using bmi forcing provider with nwm forcing configuration.")

        return self


class DataFileConfig(StrictBaseModel):
    """
    Input.config Forcing section requirement
    """
    obs_dir: Optional[str] = None
    nwmretro_file: Optional[str] = None
    hydrofab_file: Optional[str] = None
    noah_parameter_dir: Optional[str] = None
    ueb_parameter_dir: Optional[str] = None
    lasam_parameter_dir: Optional[str] = None
    lstm_parameter_dir: Optional[str] = None
    sac_sma_parameter_dir: Optional[str] = None
    snow_17_parameter_dir: Optional[str] = None
    attributes_file: Optional[str] = None
    ngen_exe_file: str
    sloth_lib: Optional[str] = None
    cfe_lib: Optional[str] = None
    lasam_lib: Optional[str] = None
    noah_owp_modular_lib: Optional[str] = None
    pet_lib: Optional[str] = None
    sac_sma_lib: Optional[str] = None
    sft_lib: Optional[str] = None
    smp_lib: Optional[str] = None
    snow_17_lib: Optional[str] = None
    topmodel_lib: Optional[str] = None
    ueb_lib: Optional[str] = None


class ParallelConfig(StrictBaseModel):
    """
    Input.config Parallel section requirement
    """
    parallel_ngen_exe: Optional[str] = None
    partition_generator_exe: Optional[str] = None
    nprocs: Optional[int] = None


class InputConfig(StrictBaseModel):
    """
    Class to organize input.config section requirements
    """
    General: Optional[GeneralConfig] = None
    ModuleProperties: Optional[ModulePropertiesConfig] = None
    Regionalization: Optional[RegionConfig] = None
    Calibration: Optional[CalibConfig] = None
    Forcing: Optional[ForcingConfig] = None
    DataFile: Optional[DataFileConfig] = None
    Parallel: Optional[ParallelConfig] = None

    # Check optional sections are present
    # only validate sections that are required for run type
    @model_validator(mode="after")
    def check_calibration(self):
        if self.General is not None and self.General.run_type == "calibration":
            if self.Calibration is None:
                raise ValueError("Calibration section is required for calibration run.")
            if isinstance(self.Calibration, dict):
                self.Calibration = CalibConfig(**self.Calibration)
        return self

    def check_regionalization(self):
        if self.General is not None and self.General.run_type == "regionalization":
            if self.Regionalization is None:
                raise ValueError("Regionalization section is required for regionalization run.")
            if isinstance(self.Regionalization, dict):
                self.Regionalization = RegionConfig(**self.Regionalization)
        return self
