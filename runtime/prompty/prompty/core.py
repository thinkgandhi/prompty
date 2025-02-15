import os
import copy
import uuid
import typing
import warnings
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path
from typing import Dict, List, Literal, Union
from .tracer import Tracer, to_dict
from .utils import get_json_type, load_json, load_json_async


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class ToolParameter:
    name: str
    type: str
    description: str
    required: bool = field(default=False)

@dataclass
class Tool:
    name: str
    type: str
    description: str
    configuration: dict[str, typing.Any]
    parameters: list[ToolParameter] = field(default_factory=list)


@dataclass
class PropertySettings:
    """PropertySettings class to define the properties of the model

    Attributes
    ----------
    type : str
        The type of the property
    default : any
        The default value of the property
    description : str
        The description of the property
    """

    type: Literal["string", "number", "array", "object", "boolean"]
    default: Union[str, int, float, list, dict, bool, None] = field(default=None)
    sample: Union[str, int, float, list, dict, bool, None] = field(default=None)
    sanitize: bool = field(default=False)
    description: str = field(default="")


@dataclass
class ModelSettings:
    """ModelSettings class to define the model of the prompty

    Attributes
    ----------
    api : str
        The api of the model
    configuration : dict
        The configuration of the model
    parameters : dict
        The parameters of the model
    response : dict
        The response of the model
    """

    api: str = field(default="")
    configuration: dict = field(default_factory=dict)
    parameters: dict = field(default_factory=dict)
    response: dict = field(default_factory=dict)


@dataclass
class TemplateSettings:
    """TemplateSettings class to define the template of the prompty

    Attributes
    ----------
    type : str
        The type of the template
    parser : str
        The parser of the template
    """

    format: str = field(default="mustache")
    parser: str = field(default="")


@dataclass
class Prompty:
    """Prompty class to define the prompty

    Attributes
    ----------
    id : str
        The id of the prompty
    name : str
        The name of the prompty
    description : str
        The description of the prompty
    authors : list[str]
        The authors of the prompty
    tags : list[str]
        The tags of the prompty
    version : str
        The version of the prompty
    base : str
        The base of the prompty
    basePrompty : Prompty
        The base prompty
    model : ModelSettings
        The model of the prompty
    inputs : dict[str, PropertySettings]
        The inputs of the prompty
    outputs : dict[str, PropertySettings]
        The outputs of the prompty
    template : TemplateSettings
        The template of the prompty
    tools:
        The tools of the prompty
    file : FilePath
        The file of the prompty
    content : Union[str, list[str], dict]
        The content of the prompty
    """

    # metadata
    id: str = field(default=uuid.uuid4().hex)
    name: str = field(default="")
    description: str = field(default="")
    authors: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    version: str = field(default="")
    base: str = field(default="")
    basePrompty: Union["Prompty", None] = field(default=None)

    # model
    model: ModelSettings = field(default_factory=ModelSettings)

    # input / output
    inputs: dict[str, PropertySettings] = field(default_factory=dict)
    outputs: dict[str, PropertySettings] = field(default_factory=dict)

    # tools
    tools: list[Tool] = field(default_factory=list)

    # template
    template: TemplateSettings = field(default_factory=TemplateSettings)

    file: Union[str, Path] = field(default="")
    content: Union[str, list[str], dict] = field(default="")

    def to_safe_dict(self) -> dict[str, typing.Any]:
        d: dict[str, typing.Any] = {}
        for field in fields(self):
            k = field.name
            v = getattr(self, field.name)
            if v != "" and v != {} and v != [] and v is not None:
                if k == "model":
                    d[k] = asdict(self.model)
                elif k == "template":
                    d[k] = asdict(self.template)
                elif k == "inputs" or k == "outputs":
                    d[k] = copy.deepcopy(v)
                elif k == "file":
                    d[k] = (
                        str(self.file.as_posix())
                        if isinstance(self.file, Path)
                        else self.file
                    )
                elif k == "tools":
                    d[k] = [asdict(t) for t in v]
                elif k == "basePrompty":
                    # no need to serialize basePrompty
                    continue

                else:
                    d[k] = v
        return d
    
    def get_sample(self) -> dict[str, typing.Any]:
        sample = {}
        for k, v in self.inputs.items():
            if v.sample:
                sample[k] = v.sample
            elif v.default:
                sample[k] = v.default
        return sample
    
    @staticmethod
    def load_property(value: typing.Any) -> PropertySettings:
        
        # if a dict, need to check if it's a PropertySettings
        if isinstance(value, dict):
            # check if dict is a PropertySettings
            # needs to contain subset of type, default, 
            # sample, sanitize, description
            if any([f.name in value for f in fields(PropertySettings)]):
                return PropertySettings(**value)
            # otherwise, assume it's a sample value
            else:
                return PropertySettings(type=get_json_type(type(value)), sample=value)
        else:
            return PropertySettings(type=get_json_type(type(value)), sample=value)
    
    @staticmethod
    def load_raw(attributes: dict, content: str, p: Path, global_config: dict) -> "Prompty":
        if "model" not in attributes:
            attributes["model"] = {}

        if "configuration" not in attributes["model"]:
            attributes["model"]["configuration"] = global_config
        else:
            attributes["model"]["configuration"] = param_hoisting(
                attributes["model"]["configuration"],
                global_config,
            )

        # pull model settings out of attributes
        try:
            model = ModelSettings(**attributes.pop("model"))
        except Exception as e:
            raise ValueError(f"Error in model settings: {e}")

        # pull template settings
        try:
            if "template" in attributes:
                t = attributes.pop("template")
                if "type" in t:
                    warnings.warn("Template type is deprecated, use format instead", DeprecationWarning)
                    t["format"] = t.pop("type")

                if isinstance(t, dict):
                    template = TemplateSettings(**t)
                # has to be a string denoting the type
                else:
                    template = TemplateSettings(format=t, parser="prompty")
            else:
                template = TemplateSettings(format="jinja2", parser="prompty")
        except Exception as e:
            raise ValueError(f"Error in template loader: {e}")

        # formalize inputs and outputs
        if "inputs" in attributes:
            try:
                inputs = {
                    k: Prompty.load_property(v) for (k, v) in attributes.pop("inputs").items()
                }
            except Exception as e:
                raise ValueError(f"Error in inputs: {e}")
        else:
            inputs = {}

        if "outputs" in attributes:
            try:
                outputs = {
                    k: Prompty.load_property(v) for (k, v) in attributes.pop("outputs").items()
                }
            except Exception as e:
                raise ValueError(f"Error in outputs: {e}")
        else:
            outputs = {}

        # infer input types
        if "sample" in attributes:
            warnings.warn("Sample is deprecated, use inputs instead", DeprecationWarning)
            sample = attributes.pop("sample")
            for k, v in sample.items():
                # implicit input
                if k not in inputs:
                    # infer v type to json type
                    inputs[k] = PropertySettings(type=get_json_type(type(v)))
                else:
                    # explicit input (overwrite type?)
                    if inputs[k].type is None:
                        inputs[k].type = get_json_type(type(v))
                    # type mismatch
                    elif inputs[k].type != get_json_type(type(v)):
                        raise ValueError(
                            f"Type mismatch for input property {k}: input type ({inputs[k].type}) != sample type ({get_json_type(type(v))})"
                        )
        else:
            sample = {}

        prompty = Prompty(
            model=model,
            inputs=inputs,
            outputs=outputs,
            template=template,
            content=content,
            file=p,
            **attributes
        )

        return prompty

    @staticmethod
    def hoist_base_prompty(top: "Prompty", base: "Prompty") -> "Prompty":
        top.name = base.name if top.name == "" else top.name
        top.description = base.description if top.description == "" else top.description
        top.authors = list(set(base.authors + top.authors))
        top.tags = list(set(base.tags + top.tags))
        top.version = base.version if top.version == "" else top.version

        top.model.api = base.model.api if top.model.api == "" else top.model.api
        top.model.configuration = param_hoisting(
            top.model.configuration, base.model.configuration
        )
        top.model.parameters = param_hoisting(
            top.model.parameters, base.model.parameters
        )
        top.model.response = param_hoisting(top.model.response, base.model.response)

        top.basePrompty = base

        # TODO: Hoist tools

        return top

    @staticmethod
    def _process_file(file: str, parent: Path) -> typing.Any:
        f = Path(parent / Path(file)).resolve().absolute()
        if f.exists():
            items = load_json(f)
            if isinstance(items, List):
                return [Prompty.normalize(value, parent) for value in items]
            elif isinstance(items, dict):
                return {
                    key: Prompty.normalize(value, parent)
                    for key, value in items.items()
                }
            else:
                return items
        else:
            raise FileNotFoundError(f"File {file} not found")

    @staticmethod
    async def _process_file_async(file: str, parent: Path) -> typing.Any:
        f = Path(parent / Path(file)).resolve().absolute()
        if f.exists():
            items = await load_json_async(f)
            if isinstance(items, list):
                return [Prompty.normalize(value, parent) for value in items]
            elif isinstance(items, dict):
                return {
                    key: Prompty.normalize(value, parent)
                    for key, value in items.items()
                }
            else:
                return items
        else:
            raise FileNotFoundError(f"File {file} not found")

    @staticmethod
    def _process_env(
        variable: str, env_error=True, default: Union[str, None] = None
    ) -> typing.Any:
        if variable in os.environ.keys():
            return os.environ[variable]
        else:
            if default:
                return default
            if env_error:
                raise ValueError(f"Variable {variable} not found in environment")

            return ""

    @staticmethod
    def normalize(attribute: typing.Any, parent: Path, env_error=True) -> typing.Any:
        if isinstance(attribute, str):
            attribute = attribute.strip()
            if attribute.startswith("${") and attribute.endswith("}"):
                # check if env or file
                variable = attribute[2:-1].split(":")
                if variable[0] == "env" and len(variable) > 1:
                    return Prompty._process_env(
                        variable[1],
                        env_error,
                        variable[2] if len(variable) > 2 else None,
                    )
                elif variable[0] == "file" and len(variable) > 1:
                    return Prompty._process_file(variable[1], parent)
                else:
                    raise ValueError(f"Invalid attribute format ({attribute})")
            else:
                return attribute
        elif isinstance(attribute, list):
            return [Prompty.normalize(value, parent) for value in attribute]
        elif isinstance(attribute, dict):
            return {
                key: Prompty.normalize(value, parent)
                for key, value in attribute.items()
            }
        else:
            return attribute

    @staticmethod
    async def normalize_async(
        attribute: typing.Any, parent: Path, env_error=True
    ) -> typing.Any:
        if isinstance(attribute, str):
            attribute = attribute.strip()
            if attribute.startswith("${") and attribute.endswith("}"):
                # check if env or file
                variable = attribute[2:-1].split(":")
                if variable[0] == "env" and len(variable) > 1:
                    return Prompty._process_env(
                        variable[1],
                        env_error,
                        variable[2] if len(variable) > 2 else None,
                    )
                elif variable[0] == "file" and len(variable) > 1:
                    return await Prompty._process_file_async(variable[1], parent)
                else:
                    raise ValueError(f"Invalid attribute format ({attribute})")
            else:
                return attribute
        elif isinstance(attribute, list):
            return [await Prompty.normalize_async(value, parent) for value in attribute]
        elif isinstance(attribute, dict):
            return {
                key: await Prompty.normalize_async(value, parent)
                for key, value in attribute.items()
            }
        else:
            return attribute


def param_hoisting(
    top: dict[str, typing.Any],
    bottom: dict[str, typing.Any],
    top_key: Union[str, None] = None,
) -> Dict[str, typing.Any]:
    if top_key:
        new_dict = {**top[top_key]} if top_key in top else {}
    else:
        new_dict = {**top}
    for key, value in bottom.items():
        if key not in new_dict:
            new_dict[key] = value
    return new_dict


class PromptyStream(Iterator):
    """PromptyStream class to iterate over LLM stream.
    Necessary for Prompty to handle streaming data when tracing."""

    def __init__(self, name: str, iterator: Iterator):
        self.name = name
        self.iterator = iterator
        self.items: list[typing.Any] = []
        self.__name__ = "PromptyStream"

    def __iter__(self):
        return self

    def __next__(self):
        try:
            # enumerate but add to list
            o = self.iterator.__next__()
            self.items.append(o)
            return o

        except StopIteration:
            # StopIteration is raised
            # contents are exhausted
            if len(self.items) > 0:
                with Tracer.start("PromptyStream") as trace:
                    trace("signature", f"{self.name}.PromptyStream")
                    trace("inputs", "None")
                    trace("result", [to_dict(s) for s in self.items])

            raise StopIteration


class AsyncPromptyStream(AsyncIterator):
    """AsyncPromptyStream class to iterate over LLM stream.
    Necessary for Prompty to handle streaming data when tracing."""

    def __init__(self, name: str, iterator: AsyncIterator):
        self.name = name
        self.iterator = iterator
        self.items: list[typing.Any] = []
        self.__name__ = "AsyncPromptyStream"

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            # enumerate but add to list
            o = await self.iterator.__anext__()
            self.items.append(o)
            return o

        except StopAsyncIteration:
            # StopIteration is raised
            # contents are exhausted
            if len(self.items) > 0:
                with Tracer.start("AsyncPromptyStream") as trace:
                    trace("signature", f"{self.name}.AsyncPromptyStream")
                    trace("inputs", "None")
                    trace("result", [to_dict(s) for s in self.items])

            raise StopAsyncIteration
