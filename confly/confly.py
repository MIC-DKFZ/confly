import sys
from pathlib import Path
from typing import Optional, Union, List
import yaml
import os
import operator
from functools import reduce
import regex
import math
import ast


GENERAL_OP_REGEX = regex.compile(r"""
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


CFG_REGEX = regex.compile(r"""
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


VAR_REGEX = regex.compile(r"""
            \$\{
                (?P<op>var)           # Only match 'cfg' literally
                \s*:\s*               # Colon with optional spaces
                (?P<arg>              # Start capturing argument
                    (?:               # Non-capturing group for content
                        [^{}]+        # Non-brace content
                        | \{ (?0) \}  # Or nested {...} recursively
                    )*
                )
            \}
        """, regex.VERBOSE)


OPERATOR_MAPPING = {
    "div": operator.truediv,
    "sqrt": None
}


class Confly:
    def __init__(self, config: Optional[Union[str, Path, dict]] = None, config_dir: Optional[Union[str, Path]] = None, args: List[str] = None, cli: bool = False):
        self.config = config
        self.config_dir = config_dir

        if isinstance(self.config, Path):
            self.config = str(self.config)

        if self.config_dir is not None:
            self.config_dir = Path(self.config_dir)
        else:
            self.config_dir = Path.cwd()

        if isinstance(self.config, str):
            arg_configs, overrides = self._parse_args(args, cli)
            self.config = self._update_config(arg_configs)
            self.config = self._interpolate(self.config, self.config, CFG_REGEX, "", overrides)
            self.config = self._update_overrides(overrides)
            self.config = self._interpolate(self.config, self.config, GENERAL_OP_REGEX, "", overrides)
            self.config = self._apply_recursively(self._maybe_convert_from_string, self.config)
        
        for key, value in self.config.items():
            setattr(self, key, Confly(value) if isinstance(value, dict) else value)
        del self.config
        del self.config_dir


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
        configs, parameters = [], {}
        for arg in args:
            if "=" in arg:
                arg = arg if arg[0] == "." else "." + arg
                arg = arg.split("=")                
                parameters[arg[0]] = arg[1]
            elif "--" in arg:
                parameters["." + arg[2:]] = True
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
        
    def _interpolate(self, obj, conf, op_regex, current_path, overrides=None):
        if overrides is not None and current_path in overrides:
            obj = overrides[current_path]
            return obj
        if isinstance(obj, dict):
            return {k: self._interpolate(v, conf, op_regex, f"{current_path}.{k}", overrides) for k, v in obj.items()}
        elif isinstance(obj, list) or isinstance(obj, tuple):
            return [self._interpolate(elem, conf, op_regex, current_path, overrides) for elem in obj]
        elif isinstance(obj, str) and self._is_entire_expression(obj, op_regex):
            expr, op, arg = self._get_expression(obj, op_regex)
            obj = self._interpolate_op(expr, op, arg, conf)
            obj = self._interpolate(obj, conf, op_regex, current_path, overrides)
            if op_regex == CFG_REGEX:
                obj = self._interpolate(obj, obj, VAR_REGEX, current_path, overrides)
            return obj
        elif isinstance(obj, str) and self._contains_expression(obj, op_regex):
            while self._contains_expression(obj, op_regex):
                expr, op, arg = self._get_expression(obj, op_regex)
                interpolated_expr = self._interpolate(expr, conf, op_regex, current_path, overrides)
                obj = obj.replace(expr, str(interpolated_expr), 1)
            return obj
        else:
            return obj

    def _is_entire_expression(self, obj: str, op_regex) -> bool:
        return bool(regex.fullmatch(op_regex, obj))

    def _contains_expression(self, obj: str, op_regex) -> bool:
        return bool(regex.search(op_regex, obj))
    
    def _get_expression(self, obj: str, op_regex):
        for m in op_regex.finditer(obj):
            expr = m.group(0)
            op = m.group("op")
            arg = m.group("arg")
            break
        return expr, op, arg
    
    def _interpolate_op(self, expr, op, arg, conf):
        if op == "var":
            return self._interpolate_var(arg, conf)
        if op == "gvar":
            return self._interpolate_var(arg, self.config)
        elif op == "cfg":
            return self._interpolate_cfg(arg)
        elif op == "env":
            return self._interpolate_env(arg)
        elif hasattr(operator, op) or hasattr(math, op) or op in OPERATOR_MAPPING:
            return self._interpolate_math(op, arg)
        else:
            return expr

    def _interpolate_var(self, obj, conf):
        keys = obj.split(".")
        interpolated_variable = conf
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
        args = self._apply_recursively(self._maybe_convert_from_string, args)
        if op == "sqrt" and len(args) == 2:
            result = str(math.pow(args[0], 1/args[1]))
        elif op in OPERATOR_MAPPING:
            op = OPERATOR_MAPPING[op]
            result = str(op(*args))
        elif hasattr(operator, op):
            op = getattr(operator, op)
            result = str(reduce(op, args))
        elif hasattr(operator, math):
            op = getattr(math, op)
            result = str(op(*args))
        else:
            raise RuntimeError(f"Operator ({op}) must be a function of 'operator', 'math' or 'OPERATOR_MAPPING'.")
        return result    

    def _update_overrides(self, overrides: list):
        """
        Update the configuration with command-line parameter overrides.

        Args:
            arg_parameters (list): List of key-value pairs (e.g., `key=value`) from the command line.
            config (dict): The current configuration to be updated.

        Returns:
            dict: The updated configuration with parameter overrides applied.
        """
        for key_path, value in overrides.items():
            key_path = key_path[1:]
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
    
    def _maybe_convert_from_string(self, s):
        s, is_converted = self._maybe_convert_to_numeric(s)
        if is_converted:
            return s
        s, is_converted = self._maybe_convert_to_none(s)
        if is_converted:
            return s
        s, is_converted = self._maybe_convert_to_boolean(s)
        if is_converted:
            return s
        s = self._maybe_convert_to_list(s)
        return s

    def _maybe_convert_to_numeric(self, s):
        """
        Convert a numeric string to an int or float, or return the original string if it's not numeric.
        
        Args:
            s (str): The input string.
        
        Returns:
            int, float, or str: Converted number if numeric, else the original string.
            bool: Whether the string is returned as number.
        """
        if not isinstance(s, str):
            return s, True
        if s.isdigit():  # Check for integers (positive)
            return int(s), True

        try:
            num = float(s)  # Convert to float (handles negative, decimals, scientific notation)
            return (int(num), True) if num.is_integer() else (num, False)  # Convert to int if there's no decimal part
        except ValueError:
            return s, False  # Return original string if not numeric  
        
    def _maybe_convert_to_none(self, s):
        if isinstance(s, str) and s == "null":
            return None, True
        else:
            return s, False
        
    def _maybe_convert_to_boolean(self, s):
        if isinstance(s, str) and s in {"True", "true"}:
            return True, True
        elif isinstance(s, str) and s in {"False", "false"}:
            return False, True
        else:
            return s, False

    def _maybe_convert_to_list(self, s: str):
        """
        Parse a Hydra-style list string (possibly nested) into a Python list.
        Examples:
        "[1,2,3]"          -> [1, 2, 3]
        "[[1,2],[3,4]]"    -> [[1, 2], [3, 4]]
        '["a","b"]'        -> ["a", "b"]
        '[[1,"x"],[2,"y"]]' -> [[1, 'x'], [2, 'y']]
        """
        if not isinstance(s, str):
            return s  # already a list or other type

        s = s.strip()

        # Quick check for list syntax
        if not (s.startswith("[") and s.endswith("]")):
            return s

        try:
            # Try to safely evaluate using Python literal syntax
            # This handles nested lists, ints, floats, strings, etc.
            value = ast.literal_eval(s)
        except (ValueError, SyntaxError):
            # Fallback: try YAML-style (in case of unquoted items)
            import yaml
            try:
                value = yaml.safe_load(s)
            except Exception as e:
                raise ValueError(f"Could not parse list: {s}") from e

        if not isinstance(value, list):
            raise ValueError(f"Parsed value is not a list: {value}")

        return value

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