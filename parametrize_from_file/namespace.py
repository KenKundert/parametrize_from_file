#!/usr/bin/env python3

import pytest
from copy import copy
from collections.abc import Mapping
from contextlib2 import nullcontext
from functools import partial
from unittest.mock import Mock

class Namespace(Mapping):
    """\
    Evaluate and/or execute snippets of python code, with powerful control over the 
    names available to those snippets.

    .. note::
    
        It is conventional to:

        - Name your namespaces: ``with_{short description}``

        - Create any namespaces you will need in a single helper file (e.g.  
          ``param_helpers.py``) to be imported in test scripts as necessary.  
          Note that namespaces are immutable, so it's safe for them to be 
          global variables.

    Examples:

        The first step when using a namespace is to specify which names it 
        should include.   This can be done using...

        ...strings (which will be `python:exec`'d):
            
            >>> with_math = Namespace('import math')
            >>> with_math.eval('math.sqrt(4)')
            2.0

        ...dictionaries:

            >>> import math
            >>> with_math = Namespace(globals())
            >>> with_math.eval('math.sqrt(4)')
            2.0

        ...modules:
            
            >>> with_math = Namespace(math)
            >>> with_math.eval('math.sqrt(4)')
            2.0

        ...other namespaces (via the constructor):

            >>> with_np = Namespace(with_math, 'import numpy as np')
            >>> with_np.eval('np.arange(3) * math.sqrt(4)')
            array([0., 2., 4.])

        ...other namespaces (via the `fork` method):

            >>> with_np = with_math.fork('import numpy as np')
            >>> with_np.eval('np.arange(3) * math.sqrt(4)')
            array([0., 2., 4.])

        ...keyword arguments:

            >>> with_math = Namespace(math=math)
            >>> with_math.eval('math.sqrt(4)')
            2.0

        ...the `star` function:

            >>> with_math = Namespace(star(math))
            >>> with_math.eval('sqrt(4)')
            2.0

        Once you have an initialized a namespace, you can use it to...

        ...evaluate expressions:

            >>> with_math.eval('sqrt(4)')
            2.0
            
        ...execute blocks of code:

            >>> ns = with_math.exec('''
            ... a = sqrt(4)
            ... b = sqrt(9)
            ... ''')
            >>> ns['a']
            2.0
            >>> ns['b']
            3.0
            >>> ns.eval('a + b')
            5.0

        ...make error-detecting context managers:

            >>> class MyError(Exception):
            ...     pass
            ...
            >>> with_err = Namespace(MyError=MyError)
            >>> err_cm = with_err.error({'type': 'MyError', 'pattern': r'\\d+'})
            >>> with err_cm:
            ...    raise MyError('404')

    If you plan to use a namespace as part of a schema, you probably want 
    `voluptuous.Namespace` instead of this class.
    """

    def __init__(self, *args, **kwargs):
        """
        Construct a namespace containing the given names.

        Arguments:
            args (str,dict,types.ModuleType):
                If string: The string will be executed as python code and any 
                names that are defined by that code will be added to the 
                namespace.  Any names added by previous arguments will be 
                available to the code.

                If dict: The items in the dictionary will the directly added to 
                the namespace.  All of the dictionary keys must be strings.

                If module: The module will be added to the namespace, with its 
                name as the key.

                The *args* are processed in order, so later *args* may 
                overwrite earlier *args*.

            kwargs:
                Each key/value pair will be added to the namespace.  The 
                *kwargs* are processed after the *args*, so if the same key is 
                defined by both, the *kwargs* definition will be used.
        """
        self._dict = {}
        _update_namespace(self._dict, *args, **kwargs)

    def __repr__(self):
        return f'{self.__class__.__name__}({self._dict.__repr__()})'

    def __getitem__(self, key):
        return self._dict.__getitem__(key)

    def __iter__(self):
        return self._dict.__iter__()

    def __len__(self):
        return self._dict.__len__()

    def fork(self, *args, **kwargs):
        """
        Create a shallow copy of this namespace.

        The arguments allow new names to be added to the new namespace.  All 
        arguments have the same meaning as in the constructor.
        """
        return self.__class__(self, *args, **kwargs)

    def eval(self, *src, eval_keys=False):
        """
        Evaluate the given expression within this namespace.
        this object.

        Arguments:
            src (str,list,dict):
                The expression (or expressions) to evaluate.  Strings are 
                directly evaluated.  List items and dict values are recursively 
                evaluated.  Dict keys are not evaluated unless *eval_keys* is 
                true.  This allows you to switch freely between structured text 
                and python syntax, depending on which makes most sense for each 
                particular input.

            eval_keys (bool):
                If true, evaluate dictionary keys.  Disabled by default because 
                most dictionary keys are strings, and it's annoying to have to 
                quote them.

            deferred (bool):
                If true, return a no-argument callable that will

        Returns:
            Any: The result of evaluating the given expressions.  If no 
            expressions were given, a callable will be returned 

        `unittest.mock.Mock` instances are handled specially by this method.  
        Specifically, they are returned unchanged (without being evaluated).  
        This special case exists because `voluptuous.Namespace.error_or` uses
        `unittest.mock.Mock` instances as placeholders when an exception is 
        expected.
        """
        src = src[0] if len(src) == 1 else list(src)
        recurse = partial(self.eval, eval_keys=eval_keys)

        if type(src) is list:
            return [recurse(x) for x in src]
        elif type(src) is dict:
            f = recurse if eval_keys else lambda x: x
            return {f(k): recurse(v) for k, v in src.items()}
        elif isinstance(src, Mock):
            return src
        else:
            return eval(src, self._dict)

    def exec(self, src):
        """
        Execute the given python snippet within this namespace.

        Arguments:
            src (str): A snippet of python code to execute.  

        Returns:
            Namespace: A new namespace containing all of the variables defined 
            in the snippet.

        `unittest.mock.Mock` instances are handled specially by this method.  
        Specifically, they are returned unchanged (without being executed).  
        This special case exists because `voluptuous.Namespace.error_or` uses
        `unittest.mock.Mock` instances as placeholders when an exception is 
        expected.
        """
        if isinstance(src, Mock):
            return src

        fork = self.fork()
        exec(src, fork._dict)
        return fork

    def exec_and_lookup(self, key):
        """
        Execute a python snippet and return a specific variable.

        Arguments:
            key (str, collections.abc.Callable):
                If string: the name of the variable to return.  
                
                If callable: The given function will be passed a dictionary 
                containing all the names defined in the given snippet.  
                Whatever that function returns will be passed on to the caller.

        Returns:
            collections.abc.Callable:
                A closure that takes a snippet of python code, executes it, and 
                returns the value indicated by the given key.  While it may 
                seem counter-intuitive for this method to return a 
                snippet-executing function instead of simply executing snippets 
                itself, this API is designed to be used when defining schemas.  
                Be aware that having schemas execute large blocks of code is 
                usually a :ref:`bad idea <schema-be-careful>`, though.
        """

        def do_exec(src):
            globals = self.exec(src)

            if callable(key):
                return key(globals)
            else:
                return globals[key]

        return do_exec

    def error(self, params):
        """\
        Create a context manager that will check that a particular error is 
        raised.

        Arguments:
            params (str, list, dict):
                This argument specifies what exception to expect (and 
                optionally how to check various aspects of it).

                If string: A string that evaluates to an exception type.  This 
                can also be ``"none"`` to specify that the returned context 
                manager should not expect any exception to be raised.

                If list: A list of the above strings (excluding ``"none"``).

                If dict: The following keys are understood:

                - "type" (required): A string or list of strings that evaluate 
                  to exception types.  The context manager will require that 
                  an exception of one of the given types is raised.

                - "message" (optional): A string or list of strings that should 
                  appear verbatim in the error message.

                - "pattern" (optional): A string or list of strings 
                  representing patterns that should appear in the error 
                  message.  Each string is interpreted as a regular expression, 
                  in the same manner as the *match* argument to 
                  `pytest.raises`.

                - "attrs" (optional): A dictionary of attributes that the 
                  exception object should have.  The dictionary keys give the 
                  attribute names, and should be strings.  The dictionary 
                  values give the attribute values, and should also be strings.  
                  Each value string will be evaluated in the context of this 
                  namespace to get the expected values.

                - "assertions" (optional): A string containing python code that 
                  will be executed when the expected exception is detected.  
                  All names available to this namespace will be available to 
                  this code.  In addition, the exception object itself will be 
                  available via the *exc* variable.  This field is typically 
                  used to make free-form assertions about the exception object.

                Note that everything is expected to be strings, because this 
                method is meant to help with parsing exception information from 
                a text file, e.g. in the NestedText_ format.  All evaluations 
                and executions are deferred for as long as possible.

        Returns:
            A context manager that can be used to check if the kind of 
            exception specified by *params* was raised.

        Examples:
            Using a built-in exception (so no need to specify globals) and not 
            checking the error message::

                >>> p = {'type': 'ZeroDivisionError'}
                >>> with Namespace().error(p):
                ...    1/0

            Using a custom exception::

                >>> class MyError(Exception):
                ...     pass
                ...
                >>> with_err = Namespace(MyError=MyError)
                >>> p = {'type': 'MyError', 'message': r'\\d+'}
                >>> with with_err.error(p):
                ...    raise MyError('404')

        Details:
            The returned context manager is re-entrant, which makes it possible 
            to stack :deco:`parametrize_from_file` invocations that make use of 
            method (e.g. via the *schema* argument).
        """

        if params == 'none':
            return ExpectSuccess()

        err = ExpectError(self)

        if isinstance(params, str):
            err.type_str = params
        else:
            def require_list(x):
                return x if isinstance(x, list) else [x]

            err.type_str = params['type']
            err.messages = require_list(params.get('message', []))
            err.patterns = require_list(params.get('pattern', []))
            err.attr_strs = params.get('attrs', {})
            err.assertions_str = params.get('assertions', {})

        return err

class ExpectSuccess(nullcontext):

    def __bool__(self):
        return False

class ExpectError:

    # Normally I'd use `@contextmanager` to make a context manager like this, 
    # but generator-based context managers cannot be reused.  This is a problem 
    # for tests, because if a test using this context manager is parametrized, 
    # the same context manager instance will need to be reused multiple times.  
    # The only way to support this is to implement the context manager from 
    # scratch.

    def __init__(self, namespace, *, type_str=Exception, messages=[], patterns=[], attr_strs={}, assertions_str=''):
        self.namespace = namespace
        self.type_str = type_str
        self.messages = messages
        self.patterns = patterns
        self.attr_strs = attr_strs
        self.assertions_str = assertions_str

    def __repr__(self):
        attrs = {
                'type': self.type_str,
                'messages': self.messages,
                'patterns': self.patterns,
                'attrs': self.attr_strs,
                'assertions': self.assertions_str,
        }
        attr_str = ' '.join(
                f'{k}={v!r}'
                for k, v in attrs.items() if v
        )
        return f'<{self.__class__.__name__} {attr_str}>'

    def __bool__(self):
        return True

    def __enter__(self):
        type = self.namespace.eval(self.type_str)
        if isinstance(type, list):
            type = tuple(type)

        self.raises_cm = pytest.raises(type)
        self.exc_info = self.raises_cm.__enter__()

    def __exit__(self, *args):
        __tracebackhide__ = True

        if self.raises_cm.__exit__(*args):
            ns = self.namespace
            exc = self.exc_info.value

            for msg in self.messages:
                assert msg in str(exc)

            for pat in self.patterns:
                self.exc_info.match(pat)

            for attr, value_str in self.attr_strs.items():
                assert hasattr(exc, attr)
                assert getattr(exc, attr) == ns.eval(value_str)

            if self.assertions_str:
                ns.fork(err=exc).exec(self.assertions_str)

            return True

def star(module):
    """
    Return a dictionary containing all public attributes exposed by the given 
    module.

    This function follows the same rules as ``from <module> import *``:

    - If the given module defines ``__all__``, only those names will be 
      used.
    - Otherwise, all names without leading underscores will be used.

    The dictionary returned by this function is meant to be used as input to 
    :py:class:`Namespace.__init__()`.
    """
    try:
        keys = module.__all__
    except AttributeError:
        keys = (k for k in module.__dict__ if not k.startswith('_'))

    return {
            k: module.__dict__[k]
            for k in keys
    }

def _update_namespace(ns_dict, *args, **kwargs):
    from inspect import ismodule

    for arg in args:
        if ismodule(arg):
            ns_dict[arg.__name__] = arg
        elif isinstance(arg, str):
            exec(arg, ns_dict)
        else:
            ns_dict.update(arg)

    ns_dict.update(kwargs)

