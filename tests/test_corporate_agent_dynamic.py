"""Read-only code boundary: generated text cannot become general Python execution."""
import pytest
from corporate_agent.dynamic import EXAMPLE,validate_code


def test_valid_native_pyrel():
    assert validate_code(EXAMPLE)
    assert validate_code(EXAMPLE.replace('hops <= 2','hops <= 2, strength >= 0.8'))


@pytest.mark.parametrize('code',[
    'import os\n'+EXAMPLE,
    EXAMPLE+'\nopen("secret")',
    EXAMPLE+'\nmodel._get_executor()',
    EXAMPLE+'\nmodel.define(Person.new(id="fake"))',
    EXAMPLE+'\nwhile True: pass',
    EXAMPLE+'\ngraph = model',
    'query = 123',
    'unused = graph.distance(from_=center)\nquery=model.where(Sources(Person)).select(Person.id)',
    EXAMPLE.replace('distance(target, connection, minimum_hops),',''),
    EXAMPLE.replace('Sources(connection),',''),
    EXAMPLE.replace('from_=center',''),
    EXAMPLE+'\nquery = query',
    EXAMPLE.replace('query = model.where(', 'distance = best_route\nquery = model.where('),
    EXAMPLE+'\nconnection.id, extra = 1, 2',
])
def test_reject_non_query_or_bypass(code):
    with pytest.raises((ValueError,SyntaxError)):
        validate_code(code)
