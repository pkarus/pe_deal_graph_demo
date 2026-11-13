"""Restricted read-only PyRel authoring surface for the Cortex agent."""
import ast

EXAMPLE = '''connection, target = Person.ref(), Person.ref()
hops = Integer.ref()
minimum_hops = Integer.ref()
strength = Float.ref()
raw_strength = Float.ref()
path = String.ref()
reason = String.ref()
distance = graph.distance(from_=center)
query = model.where(
    distance(target, connection, minimum_hops),
    Sources(connection),
    best_route(connection, hops, strength, raw_strength, path, reason),
    minimum_hops <= 3,
    hops <= 3
).select(
    connection.id.alias("connection_id"), connection.name.alias("connection"),
    target.id.alias("target_id"), target.name.alias("target"),
    strength.alias("strength"), raw_strength.alias("raw_strength"), reason.alias("reason"),
    hops.alias("hops"), minimum_hops.alias("minimum_hops"), path.alias("path")
)'''

GLOBALS={'Person','Integer','Float','String','graph','center','model','Sources','best_route','shortest_route'}
ATTRS={'ref','distance','where','select','alias','in_','id','name'}
NODE_TYPES=(ast.Module,ast.Assign,ast.Name,ast.Load,ast.Store,ast.Tuple,ast.List,ast.Call,
            ast.Attribute,ast.keyword,ast.Constant,ast.Compare,ast.Eq,ast.NotEq,ast.LtE,
            ast.Lt,ast.Gt,ast.GtE,ast.UnaryOp,ast.USub)


def validate_code(code):
    if not isinstance(code,str) or len(code)>16000:
        raise ValueError('PyRel code must be at most 16,000 characters')
    tree=ast.parse(code)
    nodes=list(ast.walk(tree))
    if len(nodes)>1200:raise ValueError('Query is too complex')
    assigned=set()
    for statement in tree.body:
        if not isinstance(statement,ast.Assign):raise ValueError('Only query variable assignments are allowed')
        for target in statement.targets:
            targets=target.elts if isinstance(target,ast.Tuple) else [target]
            for item in targets:
                if not isinstance(item,ast.Name):raise ValueError('Only local query variables may be assigned')
                if item.id in assigned:raise ValueError('Query variables cannot be reassigned')
                assigned.add(item.id)
    for node in nodes:
        if not isinstance(node,NODE_TYPES):raise ValueError(f'Unsupported syntax: {type(node).__name__}')
        if isinstance(node,ast.Name):
            if node.id.startswith('_'):raise ValueError('Private names are not allowed')
            if isinstance(node.ctx,ast.Store):
                if node.id in GLOBALS:raise ValueError('Do not replace model context variables')
        if isinstance(node,ast.Attribute) and node.attr not in ATTRS:
            raise ValueError(f'Unsupported attribute: {node.attr}; only read-only PyRel is supported')
        if isinstance(node,ast.Assign) and any(not isinstance(t,(ast.Name,ast.Tuple)) for t in node.targets):
            raise ValueError('Only local query variables may be assigned')
    for node in nodes:
        if isinstance(node,ast.Name) and isinstance(node.ctx,ast.Load) and node.id not in GLOBALS|assigned:
            raise ValueError(f'Unknown query variable: {node.id}')
    if 'query' not in assigned:raise ValueError('Assign the final model.select expression to query')
    if not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and
               isinstance(n.func.value,ast.Name) and n.func.value.id=='graph' and n.func.attr=='distance' for n in nodes):
        raise ValueError('The query must invoke native graph.distance(from_=center)')
    assignments=[n for n in tree.body if isinstance(n,ast.Assign) and
                 any(isinstance(t,ast.Name) and t.id=='query' for t in n.targets)]
    if len(assignments)!=1:raise ValueError('Assign query exactly once')
    select=assignments[0].value
    if not (isinstance(select,ast.Call) and isinstance(select.func,ast.Attribute) and select.func.attr=='select'):
        raise ValueError('query must be model.where(...).select(...)')
    where=select.func.value
    if not (isinstance(where,ast.Call) and isinstance(where.func,ast.Attribute) and where.func.attr=='where'
            and isinstance(where.func.value,ast.Name) and where.func.value.id=='model'):
        raise ValueError('query must be model.where(...).select(...)')
    distance_vars={t.id for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call)
        and isinstance(n.value.func,ast.Attribute) and n.value.func.attr=='distance'
        and isinstance(n.value.func.value,ast.Name) and n.value.func.value.id=='graph'
        and len(n.value.keywords)==1 and n.value.keywords[0].arg=='from_'
        and isinstance(n.value.keywords[0].value,ast.Name) and n.value.keywords[0].value.id=='center'
        for t in n.targets if isinstance(t,ast.Name)}
    joined={n.func.id for n in where.args if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
    if not (joined & distance_vars) or 'Sources' not in joined or len(joined & {'best_route','shortest_route'})!=1:
        raise ValueError('Join native distance(from_=center), Sources, and exactly one of best_route/shortest_route')
    return compile(tree,'<agent-authored-pyrel>','exec')


def build_query(context,code):
    from relationalai.semantics import Integer,Float,String
    namespace={'__builtins__':{},'model':context.model,'Person':context.person,
               'graph':context.graph,'center':context.focus,'Sources':context.sources,
               'best_route':context.best_route,'shortest_route':context.shortest_route,
               'Integer':Integer,'Float':Float,'String':String}
    exec(validate_code(code),namespace)
    return namespace['query']
