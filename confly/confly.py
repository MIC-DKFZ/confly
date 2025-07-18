import sys
from pathlib import Path
from typing import Optional, Union, List
import yaml
import os
import operator
from functools import reduce
import regex


class Confly:
    def __init__(self, config: Optional[Union[str, Path, dict]] = None, config_dir: Optional[Union[str, Path]] = None, args: List[str] = None, cli: bool = False):
        self.config = config
        self.config_dir = config_dir
        self.general_op_regex = regex.compile(r"""
            \$\{
                (?P<op>\w+)          # Operation name (add, mul, etc.)
                \s*:\s*              # Colon with optional spaces
                (?P<arg>            # Start capturing arguments
                    (?:              # Non-capturing group for args
                        [^{}]+       # Non-brace content
                        |            # OR
                        \{ (?0) \}   # Nested {...} recursion
                    )*
                )
            \}
        """, regex.VERBOSE)
        self.cfg_regex = regex.compile(r"""
            \$\{
                (?P<op>cfg)           # Only match 'cfg' literally
                \s*:\s*               # Colon with optional spaces
                (?P<arg>              # Start capturing argument
                    (?:               # Non-capturing group for content
                        [^{}]+        # Non-brace content
                        | \{ (?0) \}  # Or nested {...} recursively
                    )*
                )
            \}
        """, regex.VERBOSE)
        self.op_regex = None

        if isinstance(self.config, Path):
            self.config = str(self.config)

        if self.config_dir is not None:
            self.config_dir = Path(self.config_dir)
        else:
            self.config_dir = Path.cwd()

        if isinstance(self.config, str):
            # arg_configs, arg_parameters = self._parse_args(args, cli)
            # self.config = self._update_config(arg_configs)
            # self.config = self._interpolate(self.config, self._interpolate_cfg, r'\$\{cfg:\s*([^}]+)\}')
            # self.config = self._interpolate(self.config, self._interpolate_env, r'\$\{env:\s*([^}]+)\}')
            # self.config = self._update_parameters(arg_parameters)
            # self.config = self._interpolate(self.config, self._interpolate_cfg, r'\$\{cfg:\s*([^}]+)\}')
            # self.config = self._interpolate(self.config, self._interpolate_env, r'\$\{env:\s*([^}]+)\}')
            # self.config = self._interpolate(self.config, self._interpolate_var, r'\$\{var:\s*([^}]+)\}')
            # self.config = self._interpolate(self.config, self._interpolate_var, r'\$\{(add|sub|mul|div|sqrt|pow):\s*([^}]+)\}')
            # self.config = self._apply_recursively(self._maybe_convert_to_numeric, self.config)

            arg_configs, arg_parameters = self._parse_args(args, cli)
            self.config = self._update_config(arg_configs)
            self.op_regex = self.cfg_regex
            self.config = self._interpolate(self.config)
            self.config = self._update_parameters(arg_parameters)
            self.op_regex = self.general_op_regex
            self.config = self._interpolate(self.config)
            self.config = self._apply_recursively(self._maybe_convert_to_numeric, self.config)
        
        for key, value in self.config.items():
            setattr(self, key, Confly(value) if isinstance(value, dict) else value)
        del self.config
        del self.config_dir
        del self.op_regex
        del self.general_op_regex
        del self.cfg_regex


    def _parse_args(self, args, cli: bool):
        """
        Parse the command-line arguments into configuration file paths and parameters.

        Args:
            cli (bool): Whether to process command-line arguments or not.

        Returns:
            tuple: A tuple containing two lists:
                - configs (list): A list of configuration file paths provided in the command line.
                - parameters (list): A list of parameter overrides (key=value) from the command line.
        """
        if args is None:
            args = []
        if cli:
            args.append(sys.argv[1:])
        configs, parameters = [], []  
        for arg in args:
            if "=" in arg:
                parameters.append(arg)
            elif "--" in arg:
                parameters.append(arg[2:] + "=True")
            else:
                configs.append(arg)
        return configs, parameters

    def _update_config(self, arg_configs: list):
        """
        Update the initial configuration with command-line config file paths.

        Args:
            arg_configs (list): List of configuration file paths from the command line.
            init_config (str): The initial configuration to be updated.

        Returns:
            dict: A dictionary that includes the merged configuration string to be interpolated later.
        """
        config = {}
        if self.config is not None:
            arg_configs.insert(0, self.config)
        if len(arg_configs) > 0:
            config = "${cfg:" + ",".join(arg_configs) + "}"
        return config
        
    def _interpolate(self, obj):
        if isinstance(obj, dict):
            return {k: self._interpolate(v) for k, v in obj.items()}
        elif isinstance(obj, list) or isinstance(obj, tuple):
            return [self._interpolate(elem) for elem in obj]
        elif isinstance(obj, str) and self._is_entire_expression(obj):
            expr, op, arg = self._get_expression(obj)
            obj = self._interpolate_op(expr, op, arg)
            return obj
        elif isinstance(obj, str) and self._contains_expression(obj):
            while self._contains_expression(obj):
                expr, op, arg = self._get_expression(obj)
                interpolated_expr = self._interpolate(expr)
                obj = obj.replace(expr, interpolated_expr, 1)
            return obj
        else:
            return obj

    def _is_entire_expression(self, obj: str) -> bool:
        return bool(regex.fullmatch(self.op_regex, obj))

    def _contains_expression(self, obj: str) -> bool:
        return bool(regex.search(self.op_regex, obj))
    
    def _get_expression(self, obj: str):
        for m in self.op_regex.finditer(obj):
            expr = m.group(0)
            op = m.group("op")
            arg = m.group("arg")
            break
        return expr, op, arg
    
    def _interpolate_op(self, expr, op, arg):
        if op == "var":
            return self._interpolate_var(arg)
        elif op == "cfg":
            return self._interpolate_cfg(arg)
        elif op == "env":
            return self._interpolate_env(arg)
        elif hasattr(operator, op):
            return self._interpolate_math(op, arg)
        else:
            return expr

    def _interpolate_var(self, obj):
        keys = obj.split(".")
        interpolated_variable = self.config
        for key in keys:
            if key not in interpolated_variable:
                raise RuntimeError(f"Interpolation failed as {obj} is not defined.")
            interpolated_variable = interpolated_variable[key]
        return interpolated_variable

    def _interpolate_cfg(self, obj):
        obj = obj.replace(" ", "")
        configs = obj.split(",")
        config = {}
        for sub_config in configs:
            sub_config = self._load_conf(self.config_dir / sub_config)
            if isinstance(sub_config, dict) or isinstance(sub_config, list) or isinstance(sub_config, tuple):
                config.update(sub_config)
            else:
                return sub_config
            
        return config

    def _interpolate_env(self, obj):
        return os.path.expandvars("$" + obj)
    
    def _interpolate_math(self, op, args):
        args = [arg.strip() for arg in args.split(",")]
        args = self._apply_recursively(self._maybe_convert_to_numeric, args)
        op = getattr(operator, op)
        result = str(reduce(op, args))
        return result    

    def _update_parameters(self, arg_parameters: list):
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
            sub_config = self.config
            for key in keys[:-1]:
                if key not in sub_config:
                    sub_config[key] = {}
                sub_config = sub_config[key]
            sub_config[keys[-1]] = value
        return self.config

    def _load_conf(self, filepath: Path):
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

    def _maybe_convert_to_numeric(self, s):
        """
        Convert a numeric string to an int or float, or return the original string if it's not numeric.
        
        Args:
            s (str): The input string.
        
        Returns:
            int, float, or str: Converted number if numeric, else the original string.
        """
        if not isinstance(s, str):
            return s
        if s.isdigit():  # Check for integers (positive)
            return int(s)

        try:
            num = float(s)  # Convert to float (handles negative, decimals, scientific notation)
            return int(num) if num.is_integer() else num  # Convert to int if there's no decimal part
        except ValueError:
            return s  # Return original string if not numeric        

    def _apply_recursively(self, func, obj, *args):
        """
        Recursively apply a function `fn` to all non-dict, non-list values in a nested structure.

        Args:
            func (callable): Function to apply to each value.
            obj (dict | list | any): The input structure (dict, list, or value).        

        Returns:
            A new structure with the same shape and transformed values.
        """
        if isinstance(obj, dict):
            return {k: self._apply_recursively(func, v, *args) for k, v in obj.items()}
        elif isinstance(obj, list) or isinstance(obj, tuple):
            return [self._apply_recursively(func, elem, *args) for elem in obj]
        else:
            return func(obj, *args)
        
    def __repr__(self):
        return str(self.__dict__)  # Print contents nicely

    def __getitem__(self, key):
        """Enable dict-like access with square brackets (config['key'])"""
        return getattr(self, key)

    def __setitem__(self, key, value):
        """Enable dict-like assignment with square brackets (config['key'] = value)"""
        setattr(self, key, Confly(value) if isinstance(value, dict) else value)

    def __iter__(self):
        """Allow dictionary unpacking with **dotdict"""
        return iter(self.__dict__)
    
    def __len__(self):
        return len(self.__dict__)

    def items(self):
        """Make it compatible with dict.items() for unpacking"""
        return self.__dict__.items()

    def to_dict(self):
        """Convert back to a regular dictionary."""
        return {key: value.to_dict() if isinstance(value, Confly) else value 
                for key, value in self.__dict__.items()}
    
    def save(self, save_path: Union[str, Path]):
        with open(str(save_path), "w") as file:
            yaml.dump(self.to_dict(), file, default_flow_style=False, sort_keys=False)