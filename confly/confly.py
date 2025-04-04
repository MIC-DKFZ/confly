import sys
from pathlib import Path
from typing import Optional
import yaml
import os
import re

CFG_PATTERN = r"\$\{cfg:\s*([^\}]+)\}"
ENV_PATTERN = r"\$\{env:\s*([^\}]+)\}"
VAR_PATTERN = r"\$\{var:\s*([^\}]+)\}"


def confly(config: Optional[str] = None, config_dir: Optional[str] = None, cli: bool = True):
    """
    Main function to process and return the final configuration by merging
    and updating with command-line arguments and environment variables.

    Args:
        config (Optional[str]): Initial configuration to be updated.
        config_dir (Optional[str]): Directory containing the configuration files. 
            If not provided, the current directory is used.
        cli (bool): Whether to parse command-line arguments. Defaults to True.

    Returns:
        dict: The final merged and interpolated configuration.
    """
    if config_dir is not None:
        config_dir = Path(config_dir)
    else:
        config_dir = Path("")

    arg_configs, arg_parameters = parse_args(cli)
    config = update_config(arg_configs, config)
    config = interpolate(config, config, config_dir, False)
    config = update_parameters(arg_parameters, config)
    config = interpolate(config, config, config_dir, True)
    return config


def parse_args(cli: bool):
    """
    Parse the command-line arguments into configuration file paths and parameters.

    Args:
        cli (bool): Whether to process command-line arguments or not.

    Returns:
        tuple: A tuple containing two lists:
            - configs (list): A list of configuration file paths provided in the command line.
            - parameters (list): A list of parameter overrides (key=value) from the command line.
    """
    if not cli:
        return [], []    
    configs, parameters = [], []  
    for arg in sys.argv[1:]:
        if "=" in arg:
            parameters.append(arg)
        elif "--" in arg:
            parameters.append(arg[2:] + "=True")
        else:
            configs.append(arg)
    return configs, parameters


def update_config(arg_configs: list, init_config: str):
    """
    Update the initial configuration with command-line config file paths.

    Args:
        arg_configs (list): List of configuration file paths from the command line.
        init_config (str): The initial configuration to be updated.

    Returns:
        dict: A dictionary that includes the merged configuration string to be interpolated later.
    """
    config = {}
    if init_config is not None:
        arg_configs.insert(0, init_config)
    if len(arg_configs) > 0:
        config = "${cfg:" + ",".join(arg_configs) + "}"
    return config


def update_parameters(arg_parameters: list, config: dict):
    """
    Update the configuration with command-line parameter overrides.

    Args:
        arg_parameters (list): List of key-value pairs (e.g., `key=value`) from the command line.
        config (dict): The current configuration to be updated.

    Returns:
        dict: The updated configuration with parameter overrides applied.
    """
    for para in arg_parameters:
        key_path, value = para.split("=")
        keys = key_path.split(".")
        sub_config = config
        for key in keys[:-1]:
            if key not in sub_config:
                sub_config[key] = {}
            sub_config = sub_config[key]
        sub_config[keys[-1]] = maybe_convert_to_numeric(value)
    return config


def interpolate(config: dict, sub_config: dict, config_dir: Path, interpolate_variables: bool):
    """
    Recursively interpolate configuration values, resolving file references,
    environment variables, and custom variable interpolations.

    Args:
        config (dict): The main configuration being processed.
        sub_config (dict): The current sub-section of the configuration being interpolated.
        config_dir (Path): The directory containing the configuration files.
        interpolate_variables (bool): Whether to interpolate custom variables (i.e., `${var:name}`).

    Returns:
        dict: The interpolated configuration.
    """
    if isinstance(sub_config, dict):
        for key, value in sub_config.items():
            sub_config[key] = interpolate(config, value, config_dir, interpolate_variables)
    elif isinstance(sub_config, list):
        for i in range(len(sub_config)):
            sub_config[i] = interpolate(config, sub_config[i], config_dir, interpolate_variables)
    elif isinstance(sub_config, str) and len(re.findall(CFG_PATTERN, sub_config)) > 0:
        sub_config = interpolate_config(sub_config, config_dir, interpolate_variables)
    elif isinstance(sub_config, str) and len(re.findall(ENV_PATTERN, sub_config)) > 0:
        sub_config = interpolate_env(sub_config)
    elif isinstance(sub_config, str) and len(re.findall(VAR_PATTERN, sub_config)) > 0 and interpolate_variables:
        sub_config = interpolate_variable(sub_config, config)
    return sub_config


def interpolate_env(variable: str):
    matches = re.findall(ENV_PATTERN, variable)
    for match in matches:
        env_var = os.path.expandvars("$" + match)
        variable = variable.replace("${env:" + match + "}", env_var)
    return variable


def interpolate_config(variable: str, config_dir: Path, interpolate_variables: bool):
    """
    Interpolates the configuration by loading and merging configuration files.

    Args:
        variable (str): The variable containing the config file paths to interpolate.
        config_dir (Path): Directory containing the configuration files.
        interpolate_variables (bool): Whether to interpolate variables within the configurations.

    Returns:
        dict: The interpolated configuration from multiple files.
    """
    variable = variable[6:-1]
    variable = variable.replace(" ", "")
    configs = variable.split(",")
    config = {}
    for sub_config in configs:
        sub_config = load_conf(config_dir / sub_config)
        sub_config = interpolate(config, sub_config, config_dir, interpolate_variables)
        config.update(sub_config)
    return config


def interpolate_variable(variable: str, config: dict):
    """
    Interpolates a specific variable reference within the configuration.

    Args:
        variable (str): The variable to be interpolated (in dot notation).
        config (dict): The current configuration to resolve the variable from.

    Returns:
        Any: The value of the interpolated variable.

    Raises:
        RuntimeError: If the variable cannot be resolved.
    """
    variable = variable[6:-1]
    keys = variable.split(".")
    interpolated_variable = config
    for key in keys:
        if key not in interpolated_variable:
            raise RuntimeError(f"Interpolation failed as {variable} is not defined.")
        interpolated_variable = interpolated_variable[key]
    if isinstance(interpolated_variable, str) and interpolated_variable[:6] == "${var:" and interpolated_variable[-1] == "}":
        raise RuntimeError(f"Interpolation failed as {interpolated_variable} itself is not yet interpolated.")
    return interpolated_variable


def load_conf(filepath: Path):
    """
    Loads a YAML configuration file from the given filepath.

    Args:
        filepath (Path): Path to the configuration file to load.

    Returns:
        dict: The loaded configuration as a dictionary.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    if not filepath.suffix == ".yml":
        filepath = filepath.with_suffix(".yml")
    with open(filepath, 'r') as file:
        conf = yaml.safe_load(file)
    return conf


def maybe_convert_to_numeric(s):
    """
    Convert a numeric string to an int or float, or return the original string if it's not numeric.
    
    Args:
        s (str): The input string.
    
    Returns:
        int, float, or str: Converted number if numeric, else the original string.
    """
    if s.isdigit():  # Check for integers (positive)
        return int(s)

    try:
        num = float(s)  # Convert to float (handles negative, decimals, scientific notation)
        return int(num) if num.is_integer() else num  # Convert to int if there's no decimal part
    except ValueError:
        return s  # Return original string if not numeric