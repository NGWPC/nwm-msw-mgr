"""
This module contains Pydantic classes to validate input.config files for the MSWM

@author: Jeff Wade
"""

from pydantic import BaseModel, Field, field_validator, model_validator, AliasChoices
from pydantic_core.core_schema import ValidationInfo
from pathlib import Path
from typing import Optional, Literal, Union, ClassVar, List


class StrictBaseModel(BaseModel):
    """
    Custom pydantic BaseModel that checks for absent or empty strings for required variables
    """
    @model_validator(mode="before")
    # Raise errors when required variables are absent or empty strings
    def check_empty_fields(cls, values):
        """
        Reject any field whose value is an empty string or empty path.
        Runs before per-field validation on every subclass of StrictBaseModel.

        Parameters
        ---------
        values: dict of raw field name -> value pairs being validated

        Returns
        ----------
        The unmodified `values` dict, if no field is empty
        """
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

    Attributes
    ----------
    basin: basin name string
    subset_type: subset type, 'gage' or 'vpu'
    domain: domain name stringl normalized via `normalize_domain` to one of DOMAIN_MAPPINGS' values
    environment: environment for icefabric API, 'test' or 'oe'
    run_type: type of run: default, calibration, or regionalization
    models: comma-separated list of module names in the formulation, required unless run_type is 'regionalization'
    formulation: formulation name string
    main_dir: root working directory for the run
    start_period: run start time string (required for 'default/regionalization' runs if forcing engine does not set it)
    end_period: run end time string (required for 'default/regionalization' runs if forcing engine does not set it)
    output_precip: boolean flag to output precipitation
    output_swe: boolean flag to output SWE
    output_sm: boolean flag to output soil mositure
    sm_profile_depth: list of 4 monotonically increasing soil moisture profile depths (m); last must by 2.0
    sm_frac_depth: depth (m) at which to output soil moisture fraction; must match one of sm_profile_depth's values
    """
    basin: str
    subset_type: Literal["gage", "vpu"] = 'gage'
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

    DOMAIN_MAPPINGS: ClassVar[dict[str, str]] = {
        'conus': 'CONUS',
        'alaska': 'Alaska',
        'ak': 'Alaska',
        'hawaii': 'Hawaii',
        'hi': 'Hawaii',
        'puerto_rico': 'Puerto_Rico',
        'prvi': 'Puerto_Rico',
        'gl': 'Great_Lakes'}

    @field_validator("domain", mode="before")
    @classmethod
    def normalize_domain(cls, val):
        """
        Normalize the `domain` field to ints canonical value via DOMAIN_MAPPINGS

        Parameters
        ----------
        val: raw domain value supplied in input.config (case insensitive)

        Returns
        ----------
        Canonical domain string (e.g. 'CONUS', 'Alaska')
        """
        if not isinstance(val, str):
            raise ValueError(f"domain must be a string, got {type(val)}")
        normalized_val = cls.DOMAIN_MAPPINGS.get(val.lower())
        if normalized_val is None:
            raise ValueError(f"Invalid domain {repr(val)}. Valid options: {list(cls.DOMAIN_MAPPINGS)}")
        return normalized_val

    @field_validator("sm_profile_depth", mode="before")
    @classmethod
    def check_sm_profile_depth(cls, val, info: ValidationInfo):
        """Validate sm_profile_depth input.
        Must be a list of 4 monotonically increasing float values, with the last value equal to 2.0.
        If None, set to default values [0.1, 0.4, 1.0, 2.0].

        Parameters
        ----------
        val: raw sm_profile_depth value (list of floats, comma-separated string, or None)
        inf: pydantic ValidationInfo, used to read the already-validated 'output_sm' field

        Returns
        ----------
        None if `output_sm` is not True; otherwise a validated list of 4 monotonically increasing floats
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
        """
        Validate sm_frac_depth input.
        Must be a float value corresponding to one of the sm_profile_depth values.
        If None, set to default value (0.4).

        Parameters
        ----------
        val: raw sm_frac_depth value (list of floats, numeric string, or None)
        inf: pydantic ValidationInfo, used to read the already-validated 'output_sm' and `sm_profile_depth` fields

        Returns
        ----------
        None if `output_sm` is not True; otherwise a validated float matching one of sm_profile_depth's value
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
        """
        Validate that `models` is set unless `run_type` is `regionalization`

        Returns
        ----------
        self
        """
        # Models required unless run_type is regionalization
        if self.run_type != "regionalization" and not self.models:
            raise ValueError("`models` must be specified for a default and calibration runs.")

        return self


class ModulePropertiesConfig(StrictBaseModel):
    """
    Input.config module properties section requirement

    Attributes
    ----------
    cfe_aet_rootzone: CFE rootzone flag; accepts 'cfe-s_aet_rootzone', 'cfe-x_aet_rootzone', or 'cfe_aet_rootzone' as aliases, normalized to 0 or 1 via `norm_aet_rootzone`
    pet_method: integer (1-5) PET method to use
    """
    cfe_aet_rootzone: Optional[Union[int, bool, str]] = Field(None, validation_alias=AliasChoices("cfe-s_aet_rootzone", "cfe-x_aet_rootzone", "cfe_aet_rootzone"))
    pet_method: Optional[int] = None

    # Normalize is_aet_rootzone values
    @field_validator('cfe_aet_rootzone')
    def norm_aet_rootzone(cls, val):
        """
        Normalize cfe_aet_rootzone to an integer 0 or 1

        Parameters
        ----------
        val: raw cfe_aet_rootzone value (int, bool, string, or None)

        Returns
        ----------
        None if `val` is None; otherwise 1 (truthy) or 0 (falsy)
        """
        if val is None:
            return None
        if val in ('1', 1, True, "true", "True"):
            return 1
        if val in ('0', 0, False, "false", "False"):
            return 0
        raise ValueError(f"Invalid value set for cfe.aet_rootzone: {val}")


class NWMOutputConfig(StrictBaseModel):
    """
    Input.config NWM output variables section requirement

    Attributes
    ----------
    nwm_output_variables: whether to produce the full set of NWM output variables; normalized to a boolean via `norm_nwm_output`
    output_format: output format(s) for output variables ('CSV' and/or 'NetCDF'), normalized via `norm_output_format`
    """
    nwm_output_variables: Optional[Union[int, bool, str]] = None
    output_format: Optional[Union[str, List[str]]] = Field(default=["CSV"])

    # Normalize nwm_output_variables values
    @field_validator('nwm_output_variables')
    def norm_nwm_output(cls, val):
        """Normalize nwm_output_varaibles to a boolean

        Parameters
        ----------
        val: raw nwm_output_variables value (int, bool, string, or None)

        Returns
        ----------
        None if `val` is None; otherwise True or False
        """
        if val is None:
            return None
        if val in ('1', 1, True, "true", "True"):
            return True
        if val in ('0', 0, False, "false", "False"):
            return False
        raise ValueError(f"Invalid value set for nwm_output_variables: {val}")

    @field_validator('output_format')
    def norm_output_format(cls, val):
        """Normalize output_format to a list of canonical format strings ('CSV', 'NetCDF')

        Parameters
        ----------
        val: raw output_format value (comma-separated string, a list of strings, or None)

        Returns
        ----------
        None if `val` is None; otherwise a list of canonical format strings
        """
        if val is None:
            return None
        valid = {"csv": "CSV", "netcdf": "NetCDF"}
        if isinstance(val, str):
            values = [v.strip() for v in val.split(",")]
        else:
            values = val
        normalized = [v.lower() for v in values]
        invalid = [v for v in normalized if v not in valid]
        if invalid:
            raise ValueError(f"Invalid output_format value(s): {invalid}. Must be 'CSV' or 'NetCDF'")
        return [valid[v] for v in normalized]


class RegionConfig(StrictBaseModel):
    """
    Input.config regionalization section requirement

    Attributes
    ----------
    form_assign_file: path to the regionalization formulation assignment CSV file
    cat_grp_file: path to the regionalization catchment group CSV file
    """
    form_assign_file: Optional[str] = None
    cat_grp_file: Optional[str] = None


class CalibConfig(StrictBaseModel):
    """
    Input.config calibration section requirement

    Attributes
    ----------
    optimization_algorithm: calibration algorithm, 'dds', 'pso', or 'gwo': case-normalized via `case_alg`
    swarm_size: swarm/pool size; required if `optimization_algorithm is 'pso' or 'gwo'
    c1: PSO cognitive coefficient; required if `optimization_algorithm` is 'pso'
    c2: PSO social coefficient; required if `optimization_algorithm` is 'pso'
    w: PSO inertia weight; required if `optimization_algorithm` is 'pso'
    objective_function: calibration objective function name
    start_iteration: iteration number to start/resume from
    number_iteration: total number of calibration iterations to run
    restart: whether to restart calibration from a previous run (0 or 1)
    calib_output_vars: whether to write calibration output variables
    valid_output_vars: whether to write validation output variables
    calib_start_period: calibration period start time string
    calib_end_period: calibration period end time string
    calib_eval_start_period: calibration evaluation period start time string
    calib_eval_end_period: calibration evaluation period end time string
    valid_start_period: validation period start time string
    valid_end_period: validation period end time string
    valid_eval_start_period: validation evaluation period start time string
    valid_eval_end_period: validation evaluation period end time string
    full_eval_start_period: full evaluation period start tiem string
    full_eval_end_period: full evaluation period end tiem string
    save_output_iter: whether to save output each iteration (0 or 1)
    save_plot_iter_freq: frequency (in iterations) at which to save plots
    threshold_categorical: threshold value for categorical evaluation metrics
    threshold_categorical_type: 'quantile' or 'absolute'
    threshold_event: threshold value for event-based evaluation metrics
    threshold_event_type: 'quantile' or 'absolute'
    station_name: gage station name, used in evaluation site naming
    ngen_cerf: whether this calibration run is executed via ngenCERF
    calibration_run_id: ngen_cerf calibration run identifier
    auth_token: ngen_cerf authentication token
    ngencerf_base_url: ngen_cerf base URL
    user_email: user email address for run notification
    calib_parameter_file: path to the calibration parameter definition file
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
    threshold_categorical: Optional[float] = None
    threshold_categorical_type: Optional[Literal["quantile", "absolute"]] = "quantile"
    threshold_event: Optional[float] = None
    threshold_event_type: Optional[Literal["quantile", "absolute"]] = "quantile"
    station_name: Optional[str] = None
    ngen_cerf: bool
    calibration_run_id: Optional[int] = None
    auth_token: Optional[str] = None
    ngencerf_base_url: Optional[str] = None
    user_email: Optional[str] = None
    calib_parameter_file: Optional[str] = None

    # Normalize case of optimization_algorithm
    @field_validator("optimization_algorithm", mode="before")
    def case_alg(cls, value):
        """Lowercase the optimization_algorithm value, if it is a string

        Parameters
        ----------
        value: raw optimization_algorithm value

        Returns
        ----------
        Lowercased string if `value` is a string, otherwise `value` unchanged
        """
        if isinstance(value, str):
            return value.lower()
        return value

    # Check optional fields that depend on optimization_algoritm
    @model_validator(mode="after")
    def check_required_fields(self):
        """Validate fields required by the selected optimization_algorithm, plus /1 flag fields

        Returns
        ---------
        self
        """

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
                 'standard_ana_puertorico', 'medium_range_mem1', 'medium_range_mem2', 'medium_range_mem3', 'medium_range_mem4', 'medium_range_mem5',
                 'medium_range_mem6', 'medium_range_no_da',]


class ForcingConfig(StrictBaseModel):
    """
    Input.config Forcing section requirement

    Attributes
    ----------
    forcing_provider: 'csv' or 'bmi'
    forcing_dir: directory containing per-catchment forcing CSV files; required if `forcing_provder` is 'csv'
    forcing_template_dir: directory containing forcing engine yaml templates; required if `forcing_provider` is 'bmi'
    root_dir: root directory for forcing engine paths; required if `forcing_provider` is 'bmi'
    forcing_configuration: forcing engine configuration name (see `valid_configs`); required if `forcing_provider` is 'bmi'
    cycle_datetime: forecast cycle datetime string
    cold_start_datetime: datetime string marking the beginning of the cold start period
    forcing_static_dir: directory of static data files (e.g. geogrid); required if `forcing_provider` is 'bmi' and `forcing_configuration` is 'nwm'
    scratch_dir_override: if set, overrides the forcing engine template's ScratchDir value (WCOSS use case)
    forcing_product_versions: if set, overrides forcing product directory paths/versions in the forcing engine template (WCOSS use case)
    looback: optional override (minutes) of the forcing template's `LookBack` value, controlling the AnA simulation window
    """
    forcing_provider: Literal['csv', 'bmi']
    forcing_dir: Optional[str] = None
    forcing_template_dir: Optional[str] = None
    root_dir: Optional[str] = None
    forcing_configuration: Optional[str] = None
    cycle_datetime: Optional[str] = None
    cold_start_datetime: Optional[str] = None
    forcing_static_dir: Optional[str] = None
    # For WCOSS paths
    scratch_dir_override: Optional[str] = None
    forcing_product_versions: Optional[dict[str, list[str]]] = None
    # Optional override of the forcing template `LookBack` (minutes). When set,
    # replaces the `LookBack` value read from the forcing template yaml, which
    # controls the analysis (AnA) simulation window. Ignored when None.
    lookback: Optional[int] = None

    # Check optional fields that depend on forcing_provider
    @model_validator(mode="after")
    def check_required_fields(self):
        """Validate fields required by the selected forcing_provider and forcing_configuration

        Returns
        ----------
        self
        """

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

    Attributes
    ----------
    obs_dir: directory containing streamflow gage observation CSV files
    nwmretro_file: path to NWM retrospective flow file
    hydrofab_file: path to a user-provided hydrofabric geopackage (if not retrieved from Icefabric)
    noah_parameter_dir: directory containing Noah-OWP-Modular paramter table files
    ueb_parameter_dir: directory containing UEB parameter files
    lasam_parameter_dir: directory containing LASAM parameter files
    lstm_parameter_dir: directory containing LSTM static/parameter files
    ngen_exe_file: path to the ngen executable
    sloth_lib: path to the SLOTH module library file
    cfe_lib: path to the CFE module library file
    lasam_lib: path to the LASAM module library file
    noah_owp_modular_lib: path to the Noah-OWP-Modular module library file
    pet_lib: path to the PET module library file
    sac_sma_lib: path to the SAC-SMA module library file
    sft_lib: path to the SFT module library file
    smp_lib: path to the SMP module library file
    snow_17_lib: path to the Snow17 module library file
    topmodel_lib: path to the Topmodel module library file
    ueb_lib: path to the UEB module library file
    """
    obs_dir: Optional[str] = None
    nwmretro_file: Optional[str] = None
    hydrofab_file: Optional[str] = None
    noah_parameter_dir: Optional[str] = None
    ueb_parameter_dir: Optional[str] = None
    lasam_parameter_dir: Optional[str] = None
    lstm_parameter_dir: Optional[str] = None
    ngen_exe_file: Optional[str] = None
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


class DataAssimilationConfig(StrictBaseModel):
    """
    Input.config DataAssimilation section requirement

    Attributes
    ----------
    reservoir_da: whether to enable RFC reservoir data assimilation
    reservoir_rfc_dir: directory of RFC reservoir forecast time series files; required and must exist if `reservoir_da` is True
    streamflow_da: whether to enable USGS streamflow data assimilation
    usgs_timeslice_dir: directory of USGS streamflow timeslice files; required and must exist if `streamflow_da` is True
    """
    reservoir_da: bool = False
    reservoir_rfc_dir: Optional[str] = None
    streamflow_da: bool = False
    usgs_timeslice_dir: Optional[str] = None

    @model_validator(mode="after")
    def validate_reservoir_rfc_dir(self):
        """Validate that reservoir_rfc_dir is set and exists when reservoir_da is True

        Returns
        ----------
        self
        """
        if self.reservoir_da:
            if not self.reservoir_rfc_dir:
                raise ValueError("reservoir_da is True, but reservoir_rfc_dir was not provided")
            if not Path(self.reservoir_rfc_dir).exists():
                raise ValueError(f"reservoir_rfc_dir does not exist: {self.reservoir_rfc_dir}")
        return self

    @model_validator(mode="after")
    def validate_usgs_timeslice_dir(self):
        """Validate that usgs_timeslice_dir is set and exists when streamflow_da is True

        Returns
        ----------
        self
        """
        if self.streamflow_da:
            if not self.usgs_timeslice_dir:
                raise ValueError("streamflow_da is True, but usgs_timeslice_dir was not provided")
            if not Path(self.usgs_timeslice_dir).exists():
                raise ValueError(f"usgs_timeslice_dir does not exist: {self.usgs_timeslice_dir}")
        return self


class ParallelConfig(StrictBaseModel):
    """
    Input.config Parallel section requirement

    Attributes
    ----------
    parallel_ngen_exe: path to the parallel (MPI-enabled) ngen executable
    partition_generator_exe: path to the partition generator executable
    nprocs: number of paralle processes to use
    """
    parallel_ngen_exe: Optional[str] = None
    partition_generator_exe: Optional[str] = None
    nprocs: Optional[int] = None


class InputConfig(StrictBaseModel):
    """
    Class to organize input.config section requirements

    Attributes
    ----------
    General: general run configuration section
    ModuleProperties: module-specific property overrides section
    NWMOutput: NWM output variable configuration section
    Regionalization: regionalization file paths section; required if General.run_type is 'regionalization'
    Calibration: calibration settings section; required if General.run_type is 'calibration'
    Forcing: forcing engine configuration section
    DataFile: library and paramter file path section
    DataAssimilation: data assimilation configuration section
    Parallel: parallel processing configuration section
    """
    General: Optional[GeneralConfig] = None
    ModuleProperties: Optional[ModulePropertiesConfig] = None
    NWMOutput: Optional[NWMOutputConfig] = None
    Regionalization: Optional[RegionConfig] = None
    Calibration: Optional[CalibConfig] = None
    Forcing: Optional[ForcingConfig] = None
    DataFile: Optional[DataFileConfig] = None
    DataAssimilation: Optional[DataAssimilationConfig] = None
    Parallel: Optional[ParallelConfig] = None

    # Check optional sections are present
    # only validate sections that are required for run type
    @model_validator(mode="after")
    def check_calibration(self):
        """Validate that the Calibration section is present when General.run_type is 'calibration'

        Also coerces `self.Calibration` from a plain dict into a CalibConfig instance if needed.

        Returns
        ----------
        self
        """
        if self.General is not None and self.General.run_type == "calibration":
            if self.Calibration is None:
                raise ValueError("Calibration section is required for calibration run.")
            if isinstance(self.Calibration, dict):
                self.Calibration = CalibConfig(**self.Calibration)
        return self

    @model_validator(mode="after")
    def check_regionalization(self):
        """Validate that the Regionalization section is present when General.run_type is 'regionalization'

        Also coerces `self.Regionalization` from a plain dict into a RegionConfig instance if needed.

        Returns
        ----------
        self
        """
        if self.General is not None and self.General.run_type == "regionalization":
            if self.Regionalization is None:
                raise ValueError("Regionalization section is required for regionalization run.")
            if isinstance(self.Regionalization, dict):
                self.Regionalization = RegionConfig(**self.Regionalization)
        return self
