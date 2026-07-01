"""
This module contains functions to manage the configuration of NWM output variables

@author: Jeffrey Wade
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class NWMOutputVariable:
    """Represents an NWM output variable with associated metadata and provider"""
    nwm_name: str
    nwm_units: str
    description: str
    adapter: str
    adapter_var: str
    provider: List[str] = field(default_factory=list)
    provider_var: List[str] = field(default_factory=list)

    def get_provider_var(self, provider: str) -> str:
        """Return the module variable name for a given provider"""
        try:
            idx = self.provider.index(provider)
            return self.provider_var[idx]
        except ValueError:
            raise ValueError(f"Provider '{provider}' not found for variable '{self.nwm_name}'")


# Registry of NWM output variables, all must be satisfied for an NWM output formulation
NWM_OUTPUT_VARIABLES: List[NWMOutputVariable] = [
    NWMOutputVariable(
        nwm_name="sfcheadsubrt",
        nwm_units="mm",
        description="Ponded water depth",
        adapter="cfes",
        adapter_var="NWM_PONDED_DEPTH",
        provider=["cfes", "cfex", "sac", "topmodel", "lasam"],
        provider_var=["NWM_PONDED_DEPTH", "NWM_PONDED_DEPTH", "nwm_ponded_depth", "nwm_ponded_depth", "nwm_ponded_depth"],
    ),
    NWMOutputVariable(
        nwm_name="qBucket",
        nwm_units="m3/s",
        description="Flux from gw bucket",
        adapter="cfes",
        adapter_var="DEEP_GW_TO_CHANNEL_FLUX_M3_PER_S",
        provider=["cfes", "cfex", "sac", "topmodel", "lasam"],
        provider_var=["DEEP_GW_TO_CHANNEL_FLUX_M3_PER_S", "DEEP_GW_TO_CHANNEL_FLUX_M3_PER_S", "qg_m3_per_s", "land_surface_water__baseflow_volume_flux_m3_per_s", "groundwater_to_stream_recharge_m3_per_s"],
    ),
    NWMOutputVariable(
        nwm_name="ACSNOM",
        nwm_units="mm",
        description="Accumulated meltwater from bottom snow layer",
        adapter="noah",
        adapter_var="ACSNOM",
        provider=["snow17", "ueb", "noah", "topoflow-glacier"],
        provider_var=["raim_depth", "SWIT_mm", "ACSNOM", "snowpack__domain_time_integral_of_melt_volume_flux"],
    ),
    NWMOutputVariable(
        nwm_name="SNOWT_AVG",
        nwm_units="K",
        description="Average snow temperature (by layer mass)",
        adapter="noah",
        adapter_var="SNOWT_AVG",
        provider=["ueb", "noah"],
        provider_var=["Tave", "SNOWT_AVG"],
    ),
    NWMOutputVariable(
        nwm_name="SOILICE",
        nwm_units="1",
        description="Fraction of soil moisture that is ice",
        adapter="sft",
        adapter_var="soil_ice_fraction",
        provider=["sft"],
        provider_var=["soil_ice_fraction"],
    ),
    NWMOutputVariable(
        nwm_name="SOILSAT_TOP",
        nwm_units="1",
        description="Fraction of soil saturation, top 2 layers, 0.4m depth",
        adapter="smp",
        adapter_var="soil_moisture_fraction",
        provider=["smp"],
        provider_var=["soil_moisture_fraction"],
    ),
    NWMOutputVariable(
        nwm_name="QRAIN",
        nwm_units="mm/s",
        description="Rainfall rate on the ground",
        adapter="noah",
        adapter_var="QRAIN",
        provider=["noah"],
        provider_var=["QRAIN"],
    ),
    NWMOutputVariable(
        nwm_name="FSNO",
        nwm_units="1",
        description="Snow-cover fraction on the ground",
        adapter="noah",
        adapter_var="FSNO",
        provider=["noah"],
        provider_var=["FSNO"],
    ),
    NWMOutputVariable(
        nwm_name="SNOWH",
        nwm_units="m",
        description="Snow depth",
        adapter="noah",
        adapter_var="SNOWH",
        provider=["snow17", "noah", "topoflow-glacier"],
        provider_var=["snowh", "SNOWH", "snowpack__depth"],
    ),
    NWMOutputVariable(
        nwm_name="SNLIQ",
        nwm_units="mm",
        description="Snow layer liquid water",
        adapter="noah",
        adapter_var="SNLIQ",
        provider=["noah"],
        provider_var=["SNLIQ"],
    ),
    NWMOutputVariable(
        nwm_name="SNEQV",
        nwm_units="kg/m2",
        description="Snow water equivalent",
        adapter="noah",
        adapter_var="SNEQV_kg_m2",
        provider=["snow17", "ueb", "noah", "topoflow-glacier"],
        provider_var=["sneqv_kg_m2", "SWE_kg_m2", "SNEQV_kg_m2", "snowpack__liquid-equivalent_mass_per_area"],
    ),
    NWMOutputVariable(
        nwm_name="QSNOW",
        nwm_units="mm/s",
        description="Snowfall rate on the ground",
        adapter="noah",
        adapter_var="QSNOW",
        provider=["ueb", "noah", "topoflow-glacier"],
        provider_var=["Ps", "QSNOW", "atmosphere_water__snowfall_leq-volume_flux"],
    ),
    NWMOutputVariable(
        nwm_name="SOIL_T, expanded to one entry per sm_profile_depth layer",
        nwm_units="K",
        description="Soil temperature",
        adapter="sft",
        adapter_var="soil_temperature_profile",
        provider=["sft"],
        provider_var=["soil_temperature_profile"],
    ),
    NWMOutputVariable(
        nwm_name="SOIL_M",
        nwm_units="m3/m3",
        description="Volumetric soil moisture, expanded to one entry per sm_profile_depth layer",
        adapter="smp",
        adapter_var="soil_moisture_profile",
        provider=["smp"],
        provider_var=["soil_moisture_profile"],
    ),
    NWMOutputVariable(
        nwm_name="SFCRNOFF",
        nwm_units="mm",
        description="Accumulated surface runoff",
        adapter="cfes",
        adapter_var="SFCRNOFF",
        provider=["cfes", "cfex", "lasam", "sac", "topmodel"],
        provider_var=["SFCRNOFF", "SFCRNOFF", "surface_runoff", "qs", "land_surface_water__domain_time_integral_of_runoff_volume_flux"],
    ),
    NWMOutputVariable(
        nwm_name="TRAD",
        nwm_units="K",
        description="Surface radiative temperature",
        adapter="noah",
        adapter_var="TRAD",
        provider=["noah", "topoflow-glacier"],
        provider_var=["TRAD", "land_surface__temperature"],
    ),
    NWMOutputVariable(
        nwm_name="LH",
        nwm_units="W/m2",
        description="Total latent heat to the atmosphere",
        adapter="noah",
        adapter_var="LH",
        provider=["ueb", "noah"],
        provider_var=["QEs", "LH"],
    ),
    NWMOutputVariable(
        nwm_name="FIRA",
        nwm_units="W/m2",
        description="Total net LW radiation to atmosphere",
        adapter="noah",
        adapter_var="FIRA",
        provider=["ueb", "noah"],
        provider_var=["Qlns", "FIRA"],
    ),
    NWMOutputVariable(
        nwm_name="HFX",
        nwm_units="W/m2",
        description="Total sensible heat to the atmosphere",
        adapter="noah",
        adapter_var="FSH",
        provider=["ueb", "noah"],
        provider_var=["QHs", "FSH"],
    ),
]

# Lookup by variable name for quick access
NWM_OUTPUT_VARIABLE_MAP: dict = {v.nwm_name: v for v in NWM_OUTPUT_VARIABLES}


def get_provider_for_variable(variable_name: str, available_modules: List[str]) -> tuple:
    """
    Given a variable name and a list of modules in a formulation, return the matching module and its associated name.
    Fall back to the first valid provider if not match is found in available_modules

    Parameters
    ----------
    variable_name: str
        Name of the NWM output variable
    available_modules: list
        List of module names from the current formulation

    Returns
    -------
    tuple:
        (provider, modular_var) for the matched or fallback module
    """
    var = NWM_OUTPUT_VARIABLE_MAP.get(variable_name)
    if var is None:
        raise ValueError(f"Unknown NWM output variable: {variable_name}")

    # Find first matching module in registry order
    for provider in var.provider:
        if provider in available_modules:
            return provider, var.get_provider_var(provider)

    # Fallback to first valid provider if no match found
    return var.adapter, var.adapter_var


def get_providers_for_formulation(available_modules: List[str]) -> List[dict]:
    """
    For each required NWM output variable, find which module in the formulation provides it,
    falling back to the first valid provider if no match is found

    Parameters
    ----------

    available_modules: list
        List of module names from the current formulation

    Returns
    -------
    list:
        List of dicts with keys: nwm_name, nwm_units, provider, provider_var
    """
    results = []
    for var in NWM_OUTPUT_VARIABLES:
        provider, provider_var = get_provider_for_variable(var.nwm_name, available_modules)
        results.append({
            "nwm_name": var.nwm_name,
            "nwm_units": var.nwm_units,
            "provider": provider,
            "provider_var": provider_var
        })
    return results
