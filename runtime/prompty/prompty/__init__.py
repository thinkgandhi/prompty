import uuid
import typing
import traceback
from pathlib import Path
from typing import Union

from .core import (
    ModelSettings,
    Prompty,
    PropertySettings,
    TemplateSettings,
    param_hoisting,
)
from .invoker import InvokerFactory
from .parsers import PromptyChatParser
from .renderers import Jinja2Renderer, MustacheRenderer
from .tracer import trace
from .utils import (
    get_json_type,
    load_global_config,
    load_global_config_async,
    load_prompty,
    load_prompty_async,
)

InvokerFactory.add_renderer("jinja2", Jinja2Renderer)
InvokerFactory.add_renderer("mustache", MustacheRenderer)
InvokerFactory.add_parser("prompty.chat", PromptyChatParser)


@trace(description="Create a headless prompty object for programmatic use.")
def headless(
    api: str,
    content: Union[str, list[str], dict],
    configuration: dict[str, typing.Any] = {},
    parameters: dict[str, typing.Any] = {},
    connection: str = "default",
) -> Prompty:
    """Create a headless prompty object for programmatic use.

    Parameters
    ----------
    api : str
        The API to use for the model
    content : str | List[str] | dict
        The content to process
    configuration : Dict[str, any], optional
        The configuration to use, by default {}
    parameters : Dict[str, any], optional
        The parameters to use, by default {}
    connection : str, optional
        The connection to use, by default "default"

    Returns
    -------
    Prompty
        The headless prompty object

    Example
    -------
    >>> import prompty
    >>> p = prompty.headless(
            api="embedding",
            configuration={"type": "azure", "azure_deployment": "text-embedding-ada-002"},
            content="hello world",
        )
    >>> emb = prompty.execute(p)

    """

    # get caller's path (to get relative path for prompty.json)
    caller = Path(traceback.extract_stack()[-2].filename)
    templateSettings = TemplateSettings(format="NOOP", parser="NOOP")
    modelSettings = ModelSettings(
        api=api,
        configuration=Prompty.normalize(
            param_hoisting(
                configuration, load_global_config(caller.parent, connection)
            ),
            caller.parent,
        ),
        parameters=parameters,
    )

    return Prompty(model=modelSettings, template=templateSettings, content=content)


@trace(description="Create a headless prompty object for programmatic use.")
async def headless_async(
    api: str,
    content: Union[str, list[str], dict],
    configuration: dict[str, typing.Any] = {},
    parameters: dict[str, typing.Any] = {},
    connection: str = "default",
) -> Prompty:
    """Create a headless prompty object for programmatic use.

    Parameters
    ----------
    api : str
        The API to use for the model
    content : str | List[str] | dict
        The content to process
    configuration : Dict[str, any], optional
        The configuration to use, by default {}
    parameters : Dict[str, any], optional
        The parameters to use, by default {}
    connection : str, optional
        The connection to use, by default "default"

    Returns
    -------
    Prompty
        The headless prompty object

    Example
    -------
    >>> import prompty
    >>> p = await prompty.headless_async(
            api="embedding",
            configuration={"type": "azure", "azure_deployment": "text-embedding-ada-002"},
            content="hello world",
        )
    >>> emb = prompty.execute(p)

    """

    # get caller's path (to get relative path for prompty.json)
    caller = Path(traceback.extract_stack()[-2].filename)
    templateSettings = TemplateSettings(format="NOOP", parser="NOOP")

    global_config = await load_global_config_async(caller.parent, connection)
    c = await Prompty.normalize_async(
        param_hoisting(configuration, global_config), caller.parent
    )

    modelSettings = ModelSettings(
        api=api,
        configuration=c,
        parameters=parameters,
    )

    return Prompty(model=modelSettings, template=templateSettings, content=content)


@trace(description="Load a prompty file.")
def load(prompty_file: str, configuration: str = "default") -> Prompty:
    """Load a prompty file.

    Parameters
    ----------
    prompty_file : str
        The path to the prompty file
    configuration : str, optional
        The configuration to use, by default "default"

    Returns
    -------
    Prompty
        The loaded prompty object

    Example
    -------
    >>> import prompty
    >>> p = prompty.load("prompts/basic.prompty")
    >>> print(p)
    """

    p = Path(prompty_file)
    if not p.is_absolute():
        # get caller's path (take into account trace frame)
        caller = Path(traceback.extract_stack()[-3].filename)
        p = Path(caller.parent / p).resolve().absolute()

    # load dictionary from prompty file
    matter = load_prompty(p)

    attributes = matter["attributes"]
    content = matter["body"]

    # normalize attribute dictionary resolve keys and files
    attributes = Prompty.normalize(attributes, p.parent)

    # load global configuration
    global_config = Prompty.normalize(
        load_global_config(p.parent, configuration), p.parent
    )

    prompty = Prompty.load_raw(attributes, content, p, global_config)

    # recursive loading of base prompty
    if "base" in attributes:
        # load the base prompty from the same directory as the current prompty
        base = load(p.parent / attributes["base"])
        prompty = Prompty.hoist_base_prompty(prompty, base)

    return prompty


@trace(description="Load a prompty file.")
async def load_async(prompty_file: str, configuration: str = "default") -> Prompty:
    """Load a prompty file.

    Parameters
    ----------
    prompty_file : str
        The path to the prompty file
    configuration : str, optional
        The configuration to use, by default "default"

    Returns
    -------
    Prompty
        The loaded prompty object

    Example
    -------
    >>> import prompty
    >>> p = prompty.load("prompts/basic.prompty")
    >>> print(p)
    """

    p = Path(prompty_file)
    if not p.is_absolute():
        # get caller's path (take into account trace frame)
        caller = Path(traceback.extract_stack()[-3].filename)
        p = Path(caller.parent / p).resolve().absolute()

    # load dictionary from prompty file
    matter = await load_prompty_async(p)

    attributes = matter["attributes"]
    content = matter["body"]

    # normalize attribute dictionary resolve keys and files
    attributes = await Prompty.normalize_async(attributes, p.parent)

    # load global configuration
    config = await load_global_config_async(p.parent, configuration)
    global_config = await Prompty.normalize_async(config, p.parent)

    prompty = Prompty.load_raw(attributes, content, p, global_config)

    # recursive loading of base prompty
    if "base" in attributes:
        # load the base prompty from the same directory as the current prompty
        base = await load_async(p.parent / attributes["base"])
        prompty = Prompty.hoist_base_prompty(prompty, base)

    return prompty


def _validate_inputs(prompt: Prompty, inputs: dict[str, typing.Any], merge_sample: bool = False):
    if merge_sample:
        inputs = param_hoisting(inputs, prompt.get_sample())

    clean_inputs = {}
    for k, v in prompt.inputs.items():
        if k in inputs:
            if v.type != get_json_type(type(inputs[k])):
                raise ValueError(
                    f"Type mismatch for input property {k}: input type ({inputs[k].type}) != sample type ({v.type})"
                )
            clean_inputs[k] = inputs[k]
        else:
            if v.default is not None:
                clean_inputs[k] = v.default
            else:
                raise ValueError(f"Missing input property {k}")
            
    return clean_inputs

@trace(description="Prepare the inputs for the prompt.")
def prepare(
    prompt: Prompty,
    inputs: dict[str, typing.Any] = {},
    merge_sample: bool = False,
):
    """Prepare the inputs for the prompt.

    Parameters
    ----------
    prompt : Prompty
        The prompty object
    inputs : Dict[str, any], optional
        The inputs to the prompt, by default {}

    Returns
    -------
    dict
        The prepared and hidrated template shaped to the LLM model

    Example
    -------
    >>> import prompty
    >>> p = prompty.load("prompts/basic.prompty")
    >>> inputs = {"name": "John Doe"}
    >>> content = prompty.prepare(p, inputs)
    """
    values = _validate_inputs(prompt, inputs, merge_sample)

    # add nonce for this run
    prompt.template.nonce = uuid.uuid4().hex

    render = InvokerFactory.run_renderer(prompt, values, prompt.content)
    result = InvokerFactory.run_parser(prompt, render)

    return result


@trace(description="Prepare the inputs for the prompt.")
async def prepare_async(
    prompt: Prompty,
    inputs: dict[str, typing.Any] = {},
    merge_sample: bool = False,
):
    """Prepare the inputs for the prompt.

    Parameters
    ----------
    prompt : Prompty
        The prompty object
    inputs : Dict[str, any], optional
        The inputs to the prompt, by default {}

    Returns
    -------
    dict
        The prepared and hidrated template shaped to the LLM model

    Example
    -------
    >>> import prompty
    >>> p = prompty.load("prompts/basic.prompty")
    >>> inputs = {"name": "John Doe"}
    >>> content = await prompty.prepare_async(p, inputs)
    """
    values = _validate_inputs(prompt, inputs, merge_sample)

    # add nonce for this run
    prompt.template.nonce = uuid.uuid4().hex

    render = await InvokerFactory.run_renderer_async(prompt, values, prompt.content)
    result = await InvokerFactory.run_parser_async(prompt, render)

    return result


@trace(description="Run the prepared Prompty content against the model.")
def run(
    prompt: Prompty,
    content: Union[dict, list, str],
    configuration: dict[str, typing.Any] = {},
    parameters: dict[str, typing.Any] = {},
    raw: bool = False,
):
    """Run the prepared Prompty content.

    Parameters
    ----------
    prompt : Prompty
        The prompty object
    content : dict | list | str
        The content to process
    configuration : Dict[str, any], optional
        The configuration to use, by default {}
    parameters : Dict[str, any], optional
        The parameters to use, by default {}
    raw : bool, optional
        Whether to skip processing, by default False

    Returns
    -------
    any
        The result of the prompt

    Example
    -------
    >>> import prompty
    >>> p = prompty.load("prompts/basic.prompty")
    >>> inputs = {"name": "John Doe"}
    >>> content = prompty.prepare(p, inputs)
    >>> result = prompty.run(p, content)
    """

    if configuration != {}:
        prompt.model.configuration = param_hoisting(
            configuration, prompt.model.configuration
        )

    if parameters != {}:
        prompt.model.parameters = param_hoisting(parameters, prompt.model.parameters)

    result = InvokerFactory.run_executor(prompt, content)
    if not raw:
        result = InvokerFactory.run_processor(prompt, result)

    return result


@trace(description="Run the prepared Prompty content against the model.")
async def run_async(
    prompt: Prompty,
    content: Union[dict, list, str],
    configuration: dict[str, typing.Any] = {},
    parameters: dict[str, typing.Any] = {},
    raw: bool = False,
):
    """Run the prepared Prompty content.

    Parameters
    ----------
    prompt : Prompty
        The prompty object
    content : dict | list | str
        The content to process
    configuration : Dict[str, any], optional
        The configuration to use, by default {}
    parameters : Dict[str, any], optional
        The parameters to use, by default {}
    raw : bool, optional
        Whether to skip processing, by default False

    Returns
    -------
    any
        The result of the prompt

    Example
    -------
    >>> import prompty
    >>> p = prompty.load("prompts/basic.prompty")
    >>> inputs = {"name": "John Doe"}
    >>> content = await prompty.prepare_async(p, inputs)
    >>> result = await prompty.run_async(p, content)
    """

    if configuration != {}:
        prompt.model.configuration = param_hoisting(
            configuration, prompt.model.configuration
        )

    if parameters != {}:
        prompt.model.parameters = param_hoisting(parameters, prompt.model.parameters)

    result = await InvokerFactory.run_executor_async(prompt, content)
    if not raw:
        result = await InvokerFactory.run_processor_async(prompt, result)

    return result


@trace(description="Execute a prompty")
def execute(
    prompt: Union[str, Prompty],
    configuration: dict[str, typing.Any] = {},
    parameters: dict[str, typing.Any] = {},
    inputs: dict[str, typing.Any] = {},
    raw: bool = False,
    merge_sample: bool = False,
    config_name: str = "default",
):
    """Execute a prompty.

    Parameters
    ----------
    prompt : Union[str, Prompty]
        The prompty object or path to the prompty file
    configuration : Dict[str, any], optional
        The configuration to use, by default {}
    parameters : Dict[str, any], optional
        The parameters to use, by default {}
    inputs : Dict[str, any], optional
        The inputs to the prompt, by default {}
    raw : bool, optional
        Whether to skip processing, by default False
    connection : str, optional
        The connection to use, by default "default"

    Returns
    -------
    any
        The result of the prompt

    Example
    -------
    >>> import prompty
    >>> inputs = {"name": "John Doe"}
    >>> result = prompty.execute("prompts/basic.prompty", inputs=inputs)
    """
    if isinstance(prompt, (str, Path)):
        path = Path(prompt)
        if not path.is_absolute():
            # get caller's path (take into account trace frame)
            caller = Path(traceback.extract_stack()[-3].filename)
            path = Path(caller.parent / path).resolve().absolute()
        prompt = load(path, config_name)

    # prepare content
    content = prepare(prompt, inputs, merge_sample)

    # run LLM model
    result = run(prompt, content, configuration, parameters, raw)

    return result


@trace(description="Execute a prompty")
async def execute_async(
    prompt: Union[str, Prompty],
    configuration: dict[str, typing.Any] = {},
    parameters: dict[str, typing.Any] = {},
    inputs: dict[str, typing.Any] = {},
    raw: bool = False,
    merge_sample: bool = False,
    config_name: str = "default",
):
    """Execute a prompty.

    Parameters
    ----------
    prompt : Union[str, Prompty]
        The prompty object or path to the prompty file
    configuration : Dict[str, any], optional
        The configuration to use, by default {}
    parameters : Dict[str, any], optional
        The parameters to use, by default {}
    inputs : Dict[str, any], optional
        The inputs to the prompt, by default {}
    raw : bool, optional
        Whether to skip processing, by default False
    connection : str, optional
        The connection to use, by default "default"

    Returns
    -------
    any
        The result of the prompt

    Example
    -------
    >>> import prompty
    >>> inputs = {"name": "John Doe"}
    >>> result = await prompty.execute_async("prompts/basic.prompty", inputs=inputs)
    """
    if isinstance(prompt, (str, Path)):
        path = Path(prompt)
        if not path.is_absolute():
            # get caller's path (take into account trace frame)
            caller = Path(traceback.extract_stack()[-3].filename)
            path = Path(caller.parent / path).resolve().absolute()
        prompt = await load_async(path, config_name)

    # prepare content
    content = await prepare_async(prompt, inputs, merge_sample)

    # run LLM model
    result = await run_async(prompt, content, configuration, parameters, raw)

    return result
