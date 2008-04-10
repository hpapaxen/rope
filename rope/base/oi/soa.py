import rope.base.ast
import rope.base.oi.soi
import rope.base.pynames
from rope.base import pyobjects, evaluate, astutils, arguments


def analyze_module(pycore, pymodule, should_analyze,
                   search_subscopes, followed_calls):
    """Analyze `pymodule` for static object inference

    Analyzes scopes for collecting object information.  The analysis
    starts from inner scopes.

    """
    _analyze_node(pycore, pymodule, should_analyze,
                  search_subscopes, followed_calls)


def _analyze_node(pycore, pydefined, should_analyze,
                  search_subscopes, followed_calls):
    if search_subscopes(pydefined):
        for scope in pydefined.get_scope().get_scopes():
            _analyze_node(pycore, scope.pyobject, should_analyze,
                          search_subscopes, followed_calls)
    if should_analyze(pydefined):
        new_followed_calls = max(0, followed_calls - 1)
        def _called(pyfunction):
            if followed_calls:
                _analyze_node(pycore, pyfunction, should_analyze,
                              search_subscopes, new_followed_calls)
        visitor = SOIVisitor(pycore, pydefined, _called)
        for child in rope.base.ast.get_child_nodes(pydefined.get_ast()):
            rope.base.ast.walk(child, visitor)


class SOIVisitor(object):

    def __init__(self, pycore, pydefined, called_callback=None):
        self.pycore = pycore
        self.pymodule = pydefined.get_module()
        self.scope = pydefined.get_scope()
        self.called = called_callback

    def _FunctionDef(self, node):
        pass

    def _ClassDef(self, node):
        pass

    def _Call(self, node):
        for child in rope.base.ast.get_child_nodes(node):
            rope.base.ast.walk(child, self)
        primary, pyname = evaluate.get_primary_and_result(self.scope,
                                                          node.func)
        if pyname is None:
            return
        pyfunction = pyname.get_object()
        if isinstance(pyfunction, pyobjects.AbstractFunction):
            args = arguments.create_arguments(primary, pyfunction,
                                              node, self.scope)
        elif isinstance(pyfunction, pyobjects.PyClass):
            pyclass = pyfunction
            if '__init__' in pyfunction:
                pyfunction = pyfunction['__init__'].get_object()
            pyname = rope.base.pynames.UnboundName(pyobjects.PyObject(pyclass))
            args = self._args_with_self(primary, pyname, pyfunction, node)
        elif '__call__' in pyfunction:
            pyfunction = pyfunction['__call__'].get_object()
            args = self._args_with_self(primary, pyname, pyfunction, node)
        else:
            return
        self._call(pyfunction, args)

    def _args_with_self(self, primary, self_pyname, pyfunction, node):
        base_args = arguments.create_arguments(primary, pyfunction,
                                               node, self.scope)
        return arguments.MixedArguments(self_pyname, base_args, self.scope)

    def _call(self, pyfunction, args):
        if isinstance(pyfunction, pyobjects.PyFunction):
            self.pycore.object_info.function_called(
                pyfunction, args.get_arguments(pyfunction.get_param_names()))
            pyfunction._set_parameter_pyobjects(None)
            if self.called is not None:
                self.called(pyfunction)
        # XXX: Maybe we should not call every builtin function
        if isinstance(pyfunction, rope.base.builtins.BuiltinFunction):
            pyfunction.get_returned_object(args)

    def _Assign(self, node):
        for child in rope.base.ast.get_child_nodes(node):
            rope.base.ast.walk(child, self)
        visitor = _SOIAssignVisitor()
        nodes = []
        for child in node.targets:
            rope.base.ast.walk(child, visitor)
            nodes.extend(visitor.nodes)
        for subscript, levels in nodes:
            instance = evaluate.get_statement_result(self.scope, subscript.value)
            args_pynames = []
            args_pynames.append(evaluate.get_statement_result(
                                self.scope, subscript.slice.value))
            value = rope.base.oi.soi._infer_assignment(
                rope.base.pynames.AssignmentValue(node.value, levels), self.pymodule)
            args_pynames.append(rope.base.pynames.UnboundName(value))
            if instance is not None and value is not None:
                pyobject = instance.get_object()
                if '__setitem__' in pyobject:
                    pyfunction = pyobject['__setitem__'].get_object()
                    args = arguments.ObjectArguments([instance] + args_pynames)
                    self._call(pyfunction, args)
                # IDEA: handle `__setslice__`, too


class _SOIAssignVisitor(astutils._NodeNameCollector):

    def __init__(self):
        super(_SOIAssignVisitor, self).__init__()
        self.nodes = []

    def _added(self, node, levels):
        if isinstance(node, rope.base.ast.Subscript) and \
           isinstance(node.slice, rope.base.ast.Index):
            self.nodes.append((node, levels))