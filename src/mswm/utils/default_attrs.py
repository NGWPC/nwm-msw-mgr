"""Default attributes values to fill NaN NHF attributes

Some catchments in a hydrofabric geopackage's 'divides' layer may be missing values for attributes required by one of more hydrologic
models (e.g. CFE, SMP, SFT, etc.). Rather than allowing a missing value into the BMI config as NaN, `gfun.fill_divides_nan` looks up
each attribute in DEFAULT_ATTRS and substitutes the corresponding 'default' value fo r any catchment where that attribute is null.

DEFAULT_ATTRS structure
----------
Keys are NHF divide-attribute column names (lowercase, matching the geopackage's 'divides' layer schema). Each value is a dict with:
    modules: list of moudle names (as used in UI/settings, e.g. 'CFE', 'SFT', 'SMP') that consume this attribute. An attribute may be
        shared by multiple modules.
    default: the numeric value substituted for this attribute wherever it is NaN in the divides layer.
"""

DEFAULT_ATTRS = {
    'cgw': {
        'modules': ['CFE'],
        'default': 1.8E-05,
    },
    'expon': {
        'modules': ['CFE'],
        'default': 3,
    },
    'max_gw_storage': {
        'modules': ['CFE'],
        'default': 0.05,
    },
    'refkdt_mean': {
        'modules': ['CFE'],
        'default': 1,
    },
    'dksat_geomean': {
        'modules': ['CFE'],
        'default': 3.38E-06,
    },
    'slope1km_mean': {
        'modules': ['CFE'],
        'default': 0.05,
    },
    'smcwlt_mean': {
        'modules': ['CFE'],
        'default': 0.05,
    },
    'a_xinanjiang_inflection_point_parameter': {
        'modules': ['CFE'],
        'default': 0.001,
    },
    'b_xinanjiang_shape_parameter': {
        'modules': ['CFE'],
        'default': 0.261,
    },
    'x_xinanjiang_shape_parameter': {
        'modules': ['CFE'],
        'default': 0.182,
    },
    'psisat_geomean': {
        'modules': ['CFE', 'SFT', 'SMP'],
        'default': 0.355,
    },
    'smcmax_mean': {
        'modules': ['CFE', 'SFT', 'SMP'],
        'default': 0.439,
    },
    'bexp_mode': {
        'modules': ['CFE', 'SFT', 'SMP'],
        'default': 4.05,
    },
    'quartz_mean': {
        'modules': ['SFT'],
        'default': 0.5,
    },
    'mfmax_mean': {
        'modules': ['snow17'],
        'default': 1,
    },
    'mfmin_mean': {
        'modules': ['snow17'],
        'default': 0.2,
    },
    'uadj_mean': {
        'modules': ['snow17'],
        'default': 0.05,
    },
    'uztwm_mean': {
        'modules': ['sac'],
        'default': 75,
    },
    'uzfwm_mean': {
        'modules': ['sac'],
        'default': 30,
    },
    'lztwm_mean': {
        'modules': ['sac'],
        'default': 150,
    },
    'lzfpm_mean': {
        'modules': ['sac'],
        'default': 300,
    },
    'lzfsm_mean': {
        'modules': ['sac'],
        'default': 150,
    },
    'uzk_mean': {
        'modules': ['sac'],
        'default': 0.3,
    },
    'lzpk_mean': {
        'modules': ['sac'],
        'default': 0.01,
    },
    'lzsk_mean': {
        'modules': ['sac'],
        'default': 0.1,
    },
    'zperc_mean': {
        'modules': ['sac'],
        'default': 100,
    },
    'rexp_mean': {
        'modules': ['sac'],
        'default': 3,
    },
    'pfree_mean': {
        'modules': ['sac'],
        'default': 0.1,
    },
    'twi_q25': {
        'modules': ['TOPMODEL'],
        'default': 5,
    },
    'twi_q50': {
        'modules': ['TOPMODEL'],
        'default': 5.5,
    },
    'twi_q75': {
        'modules': ['TOPMODEL'],
        'default': 6,
    },
    'twi_q100': {
        'modules': ['TOPMODEL'],
        'default': 8,
    },
}
