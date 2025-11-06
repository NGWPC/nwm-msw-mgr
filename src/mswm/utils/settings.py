import pandas as pd

DEFAULT_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


# information about all modules currently supported in ngen-cal
# Column 1: module name
# Column 2: name used by the UI (API/GUI/CLI)
# Column 3: name used in config files (calibration parameter file, 'model_type_name' in realization file)
# Column 4: relevant hydrologic process(es). Note the correct order of processes:
#    SLOTH, Evapotranspiration, Glacier_snow, Soil Moisture, Rainfal_runoff, Routing
# Column 5: whether the module has calibratable parameters

modules_all = pd.DataFrame([('sloth', 'sloth', 'SLOTH', ['SLOTH'], False),
                            ('pet', 'pet', 'PET', ['Evapotranspiration'], False),
                            ('topoflow', 'topoflow', 'topoflow', ['Glacier_snow', 'Evapotranspiration', 'Rainfall_runoff'], True),
                            ('noah', 'noah-owp-modular', 'NoahOWP', ['Glacier_snow', 'Evapotranspiration'], True),
                            ('snow17', 'snow-17', 'snow17', ['Glacier_snow'], True),
                            ('ueb', 'ueb', 'UEB', ['Glacier_snow'], True),
                            ('sft', 'sft', 'SFT', ['Soil_moisture'], False),
                            ('smp', 'smp', 'SMP', ['Soil_moisture'], False),
                            ('cfes', 'cfe-s', 'CFE', ['Rainfall_runoff'], True),
                            ('cfex', 'cfe-x', 'CFE', ['Rainfall_runoff'], True),
                            ('sac', 'sac-sma', 'sac', ['Rainfall_runoff'], True),
                            ('lasam', 'lasam', 'LASAM', ['Rainfall_runoff'], True),
                            ('topmodel', 'topmodel', 'TOPMODEL', ['Rainfall_runoff'], True),
                            ('lstm', 'lstm', 'bmi_LSTM', ['Glacier_snow', 'Evapotranspiration', 'Rainfall_runoff'], False),
                            ('troute', 't-route', 'troute', ['Routing'], False)],
                           columns=['module', 'name_ui', 'name_config', 'process', 'calibratable'])
